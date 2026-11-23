#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <vulkan/vulkan.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <string>
#include <vector>

#include "MinHook.h"
#include "imgui.h"
#include "imgui_impl_win32.h"
#include "imgui_impl_vulkan.h"
#include "udp_gc_listener.h"

namespace {

using PFN_vkCreateInstance = VkResult(VKAPI_PTR*)(
    const VkInstanceCreateInfo* pCreateInfo,
    const VkAllocationCallbacks* pAllocator, VkInstance* pInstance);
using PFN_vkCreateDevice = VkResult(VKAPI_PTR*)(
    VkPhysicalDevice physicalDevice, const VkDeviceCreateInfo* pCreateInfo,
    const VkAllocationCallbacks* pAllocator, VkDevice* pDevice);
using PFN_vkCreateSwapchainKHR = VkResult(VKAPI_PTR*)(
    VkDevice device, const VkSwapchainCreateInfoKHR* pCreateInfo,
    const VkAllocationCallbacks* pAllocator, VkSwapchainKHR* pSwapchain);
using PFN_vkQueuePresentKHR = VkResult(VKAPI_PTR*)(
    VkQueue queue, const VkPresentInfoKHR* pPresentInfo);

UdpGcListener g_gc_listener(49152, 49153);
std::atomic<bool> g_worker_active{false};
HANDLE g_init_thread = nullptr;

PFN_vkCreateInstance g_orig_vkCreateInstance = nullptr;
PFN_vkCreateDevice g_orig_vkCreateDevice = nullptr;
PFN_vkCreateSwapchainKHR g_orig_vkCreateSwapchainKHR = nullptr;
PFN_vkQueuePresentKHR g_orig_vkQueuePresentKHR = nullptr;

bool g_mh_initialized = false;
bool g_imgui_initialized = false;
HWND g_target_hwnd = nullptr;

struct VulkanOverlayContext {
  VkInstance instance = VK_NULL_HANDLE;
  VkPhysicalDevice physical_device = VK_NULL_HANDLE;
  VkDevice device = VK_NULL_HANDLE;
  uint32_t queue_family = 0;
  VkQueue queue = VK_NULL_HANDLE;
  VkDescriptorPool descriptor_pool = VK_NULL_HANDLE;
  VkRenderPass render_pass = VK_NULL_HANDLE;
  VkCommandPool command_pool = VK_NULL_HANDLE;
  std::vector<VkCommandBuffer> command_buffers;
  uint32_t min_image_count = 2;
  uint32_t image_count = 2;
  VkSampleCountFlagBits msaa_samples = VK_SAMPLE_COUNT_1_BIT;
  bool ready = false;
};

VulkanOverlayContext g_vk_ctx{};

BOOL CALLBACK FindProcessWindowProc(HWND hwnd, LPARAM lParam) {
  auto* out_hwnd = reinterpret_cast<HWND*>(lParam);
  DWORD window_pid = 0;
  GetWindowThreadProcessId(hwnd, &window_pid);
  if (window_pid == GetCurrentProcessId() && IsWindowVisible(hwnd) &&
      GetWindow(hwnd, GW_OWNER) == nullptr) {
    *out_hwnd = hwnd;
    return FALSE;
  }
  return TRUE;
}

HWND FindCurrentProcessMainWindow() {
  HWND found = nullptr;
  EnumWindows(FindProcessWindowProc, reinterpret_cast<LPARAM>(&found));
  return found;
}

bool HasButtonPressed(const GcPadState& pad, const char* button_name) {
  return std::find(pad.botones.begin(), pad.botones.end(), button_name) !=
         pad.botones.end();
}

void DrawPlayerSummary(int player_num, const GcPadState& pad) {
  ImGui::Text("P%d: %s", player_num, pad.connected ? "Conectado" : "Inactivo");
  ImGui::Text("Stick: (%d, %d) | C-Stick: (%d, %d)", pad.stick_x, pad.stick_y,
              pad.c_stick_x, pad.c_stick_y);
  ImGui::Text("L: %d | R: %d", pad.l_analog, pad.r_analog);
  ImGui::Text("Botones: A=%d B=%d X=%d Y=%d Z=%d Start=%d",
              HasButtonPressed(pad, "A") ? 1 : 0,
              HasButtonPressed(pad, "B") ? 1 : 0,
              HasButtonPressed(pad, "X") ? 1 : 0,
              HasButtonPressed(pad, "Y") ? 1 : 0,
              HasButtonPressed(pad, "Z") ? 1 : 0,
              HasButtonPressed(pad, "Start") ? 1 : 0);
}

void RenderGcOverlay(const GcPadState& p1, const GcPadState& p2) {
  ImGui::SetNextWindowPos(ImVec2(16.0f, 16.0f), ImGuiCond_FirstUseEver);
  ImGui::Begin("GC Overlay", nullptr,
               ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize |
                   ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoFocusOnAppearing |
                   ImGuiWindowFlags_NoNav);
  DrawPlayerSummary(1, p1);
  ImGui::Separator();
  DrawPlayerSummary(2, p2);
  ImGui::End();
}

bool EnsureDescriptorPool() {
  if (g_vk_ctx.descriptor_pool != VK_NULL_HANDLE) {
    return true;
  }
  if (g_vk_ctx.device == VK_NULL_HANDLE) {
    return false;
  }

  VkDescriptorPoolSize pool_sizes[] = {
      {VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 32},
  };

  VkDescriptorPoolCreateInfo pool_info{};
  pool_info.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
  pool_info.flags = VK_DESCRIPTOR_POOL_CREATE_FREE_DESCRIPTOR_SET_BIT;
  pool_info.maxSets = 32;
  pool_info.poolSizeCount =
      static_cast<uint32_t>(sizeof(pool_sizes) / sizeof(pool_sizes[0]));
  pool_info.pPoolSizes = pool_sizes;

  return vkCreateDescriptorPool(g_vk_ctx.device, &pool_info, nullptr,
                                &g_vk_ctx.descriptor_pool) == VK_SUCCESS;
}

bool EnsureCommandResources() {
  if (g_vk_ctx.device == VK_NULL_HANDLE) {
    return false;
  }

  const uint32_t count = (g_vk_ctx.image_count > 0) ? g_vk_ctx.image_count : 2;

  if (g_vk_ctx.command_pool == VK_NULL_HANDLE) {
    VkCommandPoolCreateInfo pool_info{};
    pool_info.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    pool_info.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    pool_info.queueFamilyIndex = g_vk_ctx.queue_family;

    if (vkCreateCommandPool(g_vk_ctx.device, &pool_info, nullptr,
                            &g_vk_ctx.command_pool) != VK_SUCCESS) {
      return false;
    }
  }

  if (g_vk_ctx.command_buffers.size() != count) {
    if (!g_vk_ctx.command_buffers.empty()) {
      vkFreeCommandBuffers(
          g_vk_ctx.device, g_vk_ctx.command_pool,
          static_cast<uint32_t>(g_vk_ctx.command_buffers.size()),
          g_vk_ctx.command_buffers.data());
      g_vk_ctx.command_buffers.clear();
    }

    g_vk_ctx.command_buffers.resize(count, VK_NULL_HANDLE);
    VkCommandBufferAllocateInfo alloc_info{};
    alloc_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    alloc_info.commandPool = g_vk_ctx.command_pool;
    alloc_info.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    alloc_info.commandBufferCount = count;

    if (vkAllocateCommandBuffers(g_vk_ctx.device, &alloc_info,
                               g_vk_ctx.command_buffers.data()) !=
        VK_SUCCESS) {
      g_vk_ctx.command_buffers.clear();
      return false;
    }
  }

  return true;
}

void UpdateContextReadyState() {
  g_vk_ctx.ready = (g_vk_ctx.instance != VK_NULL_HANDLE) &&
                   (g_vk_ctx.physical_device != VK_NULL_HANDLE) &&
                   (g_vk_ctx.device != VK_NULL_HANDLE) &&
                   (g_vk_ctx.queue != VK_NULL_HANDLE) &&
                   (g_vk_ctx.render_pass != VK_NULL_HANDLE) &&
                   EnsureDescriptorPool() && EnsureCommandResources();
}

bool EnsureImGuiInitialized(VkQueue queue, const VkPresentInfoKHR* pPresentInfo) {
  if (g_imgui_initialized) {
    return true;
  }
  (void)pPresentInfo;

  if (queue != VK_NULL_HANDLE && g_vk_ctx.queue == VK_NULL_HANDLE) {
    g_vk_ctx.queue = queue;
  }

  if (g_target_hwnd == nullptr) {
    g_target_hwnd = FindCurrentProcessMainWindow();
  }

  UpdateContextReadyState();

  if (g_target_hwnd == nullptr || !g_vk_ctx.ready) {
    return false;
  }

  IMGUI_CHECKVERSION();
  ImGui::CreateContext();
  ImGuiIO& io = ImGui::GetIO();
  io.IniFilename = nullptr;

  if (!ImGui_ImplWin32_Init(g_target_hwnd)) {
    ImGui::DestroyContext();
    return false;
  }

  ImGui_ImplVulkan_InitInfo init_info{};
  init_info.ApiVersion = VK_API_VERSION_1_3;
  init_info.Instance = g_vk_ctx.instance;
  init_info.PhysicalDevice = g_vk_ctx.physical_device;
  init_info.Device = g_vk_ctx.device;
  init_info.QueueFamily = g_vk_ctx.queue_family;
  init_info.Queue = g_vk_ctx.queue;
  init_info.DescriptorPool = g_vk_ctx.descriptor_pool;
  init_info.MinImageCount = g_vk_ctx.min_image_count;
  init_info.ImageCount = g_vk_ctx.image_count;
  init_info.PipelineInfoMain.RenderPass = g_vk_ctx.render_pass;
  init_info.PipelineInfoMain.MSAASamples = g_vk_ctx.msaa_samples;

  if (!ImGui_ImplVulkan_Init(&init_info)) {
    ImGui_ImplWin32_Shutdown();
    ImGui::DestroyContext();
    return false;
  }

  g_imgui_initialized = true;
  return true;
}

void RecordImGuiDrawCommands(ImDrawData* draw_data, VkQueue queue,
                             const VkPresentInfoKHR* pPresentInfo) {
  if (draw_data == nullptr || draw_data->CmdListsCount == 0 ||
      g_vk_ctx.device == VK_NULL_HANDLE ||
      g_vk_ctx.command_buffers.empty()) {
    return;
  }

  uint32_t frame_idx = 0;
  if (pPresentInfo != nullptr && pPresentInfo->pImageIndices != nullptr &&
      pPresentInfo->swapchainCount > 0) {
    frame_idx = pPresentInfo->pImageIndices[0] %
                static_cast<uint32_t>(g_vk_ctx.command_buffers.size());
  }

  VkCommandBuffer cmd = g_vk_ctx.command_buffers[frame_idx];
  vkResetCommandBuffer(cmd, 0);

  VkCommandBufferBeginInfo begin_info{};
  begin_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
  begin_info.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;

  if (vkBeginCommandBuffer(cmd, &begin_info) != VK_SUCCESS) {
    return;
  }

  ImGui_ImplVulkan_RenderDrawData(draw_data, cmd);

  if (vkEndCommandBuffer(cmd) != VK_SUCCESS) {
    return;
  }

  VkSubmitInfo submit_info{};
  submit_info.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
  submit_info.commandBufferCount = 1;
  submit_info.pCommandBuffers = &cmd;

  vkQueueSubmit(queue, 1, &submit_info, VK_NULL_HANDLE);
}

VkResult VKAPI_PTR Hooked_vkCreateInstance(
    const VkInstanceCreateInfo* pCreateInfo,
    const VkAllocationCallbacks* pAllocator, VkInstance* pInstance) {
  VkResult res = g_orig_vkCreateInstance(pCreateInfo, pAllocator, pInstance);
  if (res == VK_SUCCESS && pInstance != nullptr &&
      *pInstance != VK_NULL_HANDLE) {
    g_vk_ctx.instance = *pInstance;
    UpdateContextReadyState();
  }
  return res;
}

VkResult VKAPI_PTR Hooked_vkCreateDevice(
    VkPhysicalDevice physicalDevice, const VkDeviceCreateInfo* pCreateInfo,
    const VkAllocationCallbacks* pAllocator, VkDevice* pDevice) {
  VkResult res =
      g_orig_vkCreateDevice(physicalDevice, pCreateInfo, pAllocator, pDevice);
  if (res == VK_SUCCESS && pDevice != nullptr && *pDevice != VK_NULL_HANDLE) {
    g_vk_ctx.physical_device = physicalDevice;
    g_vk_ctx.device = *pDevice;
    if (pCreateInfo != nullptr && pCreateInfo->queueCreateInfoCount > 0 &&
        pCreateInfo->pQueueCreateInfos != nullptr) {
      g_vk_ctx.queue_family = pCreateInfo->pQueueCreateInfos[0].queueFamilyIndex;
      vkGetDeviceQueue(g_vk_ctx.device, g_vk_ctx.queue_family, 0,
                       &g_vk_ctx.queue);
    }
    UpdateContextReadyState();
  }
  return res;
}

VkResult VKAPI_PTR Hooked_vkCreateSwapchainKHR(
    VkDevice device, const VkSwapchainCreateInfoKHR* pCreateInfo,
    const VkAllocationCallbacks* pAllocator, VkSwapchainKHR* pSwapchain) {
  VkResult res = g_orig_vkCreateSwapchainKHR(device, pCreateInfo, pAllocator,
                                              pSwapchain);
  if (res == VK_SUCCESS && pCreateInfo != nullptr) {
    if (g_vk_ctx.device == VK_NULL_HANDLE) {
      g_vk_ctx.device = device;
    }
    g_vk_ctx.min_image_count =
        (pCreateInfo->minImageCount >= 2) ? pCreateInfo->minImageCount : 2;
    g_vk_ctx.image_count = g_vk_ctx.min_image_count;

    uint32_t img_count = 0;
    if (pSwapchain != nullptr && *pSwapchain != VK_NULL_HANDLE &&
        vkGetSwapchainImagesKHR(device, *pSwapchain, &img_count, nullptr) ==
            VK_SUCCESS &&
        img_count > 0) {
      g_vk_ctx.image_count = img_count;
    }
    UpdateContextReadyState();
  }
  return res;
}

VkResult VKAPI_PTR Hooked_vkQueuePresentKHR(
    VkQueue queue, const VkPresentInfoKHR* pPresentInfo) {
  GcPadState p1 = g_gc_listener.GetPlayerState(1);
  GcPadState p2 = g_gc_listener.GetPlayerState(2);

  if (EnsureImGuiInitialized(queue, pPresentInfo)) {
    ImGui_ImplVulkan_NewFrame();
    ImGui_ImplWin32_NewFrame();
    ImGui::NewFrame();

    RenderGcOverlay(p1, p2);

    ImGui::Render();
    ImDrawData* draw_data = ImGui::GetDrawData();
    if (draw_data != nullptr && draw_data->CmdListsCount > 0) {
      RecordImGuiDrawCommands(draw_data, queue, pPresentInfo);
    }
  }

  if (g_orig_vkQueuePresentKHR != nullptr) {
    return g_orig_vkQueuePresentKHR(queue, pPresentInfo);
  }
  return VK_SUCCESS;
}

bool HookFunction(HMODULE vk_mod, const char* func_name, void* detour,
                  void** original) {
  auto addr = reinterpret_cast<void*>(GetProcAddress(vk_mod, func_name));
  if (addr == nullptr) {
    return false;
  }
  if (MH_CreateHook(addr, detour, original) != MH_OK) {
    return false;
  }
  return MH_EnableHook(addr) == MH_OK;
}

bool InstallVulkanHooks() {
  HMODULE vk_mod = GetModuleHandleA("vulkan-1.dll");
  if (vk_mod == nullptr) {
    return false;
  }

  if (!g_mh_initialized) {
    if (MH_Initialize() != MH_OK) {
      return false;
    }
    g_mh_initialized = true;
  }

  HookFunction(vk_mod, "vkCreateInstance",
               reinterpret_cast<void*>(&Hooked_vkCreateInstance),
               reinterpret_cast<void**>(&g_orig_vkCreateInstance));
  HookFunction(vk_mod, "vkCreateDevice",
               reinterpret_cast<void*>(&Hooked_vkCreateDevice),
               reinterpret_cast<void**>(&g_orig_vkCreateDevice));
  HookFunction(vk_mod, "vkCreateSwapchainKHR",
               reinterpret_cast<void*>(&Hooked_vkCreateSwapchainKHR),
               reinterpret_cast<void**>(&g_orig_vkCreateSwapchainKHR));

  if (!HookFunction(vk_mod, "vkQueuePresentKHR",
                    reinterpret_cast<void*>(&Hooked_vkQueuePresentKHR),
                    reinterpret_cast<void**>(&g_orig_vkQueuePresentKHR))) {
    return false;
  }

  return true;
}

void ShutdownVulkanAndImGui() {
  if (g_imgui_initialized) {
    ImGui_ImplVulkan_Shutdown();
    ImGui_ImplWin32_Shutdown();
    ImGui::DestroyContext();
    g_imgui_initialized = false;
  }

  if (g_vk_ctx.device != VK_NULL_HANDLE) {
    vkDeviceWaitIdle(g_vk_ctx.device);
    if (!g_vk_ctx.command_buffers.empty() &&
        g_vk_ctx.command_pool != VK_NULL_HANDLE) {
      vkFreeCommandBuffers(
          g_vk_ctx.device, g_vk_ctx.command_pool,
          static_cast<uint32_t>(g_vk_ctx.command_buffers.size()),
          g_vk_ctx.command_buffers.data());
      g_vk_ctx.command_buffers.clear();
    }
    if (g_vk_ctx.command_pool != VK_NULL_HANDLE) {
      vkDestroyCommandPool(g_vk_ctx.device, g_vk_ctx.command_pool, nullptr);
      g_vk_ctx.command_pool = VK_NULL_HANDLE;
    }
    if (g_vk_ctx.descriptor_pool != VK_NULL_HANDLE) {
      vkDestroyDescriptorPool(g_vk_ctx.device, g_vk_ctx.descriptor_pool,
                              nullptr);
      g_vk_ctx.descriptor_pool = VK_NULL_HANDLE;
    }
  }

  if (g_mh_initialized) {
    MH_DisableHook(MH_ALL_HOOKS);
    MH_Uninitialize();
    g_mh_initialized = false;
  }
}

DWORD WINAPI OverlayWorkerThread(LPVOID) {
  g_worker_active.store(true);
  g_gc_listener.Start();

  while (g_worker_active.load()) {
    if (InstallVulkanHooks()) {
      break;
    }
    Sleep(100);
  }

  while (g_worker_active.load()) {
    Sleep(50);
  }

  ShutdownVulkanAndImGui();
  g_gc_listener.Stop();
  return 0;
}

}  // namespace

extern "C" __declspec(dllexport) GcPadState ReadGcOverlayState(int player) {
  return g_gc_listener.GetPlayerState(player);
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call,
                    LPVOID lpReserved) {
  (void)lpReserved;
  switch (ul_reason_for_call) {
    case DLL_PROCESS_ATTACH:
      DisableThreadLibraryCalls(hModule);
      g_worker_active.store(true);
      g_init_thread = CreateThread(nullptr, 0, OverlayWorkerThread, hModule, 0,
                                   nullptr);
      if (g_init_thread == nullptr) {
        g_worker_active.store(false);
        return FALSE;
      }
      break;

    case DLL_PROCESS_DETACH:
      g_worker_active.store(false);
      if (g_init_thread != nullptr) {
        WaitForSingleObject(g_init_thread, 2000);
        CloseHandle(g_init_thread);
        g_init_thread = nullptr;
      }
      g_gc_listener.Stop();
      break;
  }
  return TRUE;
}