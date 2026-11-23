#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <vulkan/vulkan.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <string>

#include "MinHook.h"
#include "imgui.h"
#include "imgui_impl_win32.h"
#include "imgui_impl_vulkan.h"
#include "udp_gc_listener.h"

namespace {

using PFN_vkQueuePresentKHR = VkResult(VKAPI_PTR*)(VkQueue queue,
                                                  const VkPresentInfoKHR* pPresentInfo);

UdpGcListener g_gc_listener(49152, 49153);
std::atomic<bool> g_worker_active{false};
HANDLE g_init_thread = nullptr;

PFN_vkQueuePresentKHR g_orig_vkQueuePresentKHR = nullptr;
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

bool EnsureImGuiInitialized(VkQueue queue, const VkPresentInfoKHR* pPresentInfo) {
  if (g_imgui_initialized) {
    return true;
  }
  (void)queue;
  (void)pPresentInfo;

  if (g_target_hwnd == nullptr) {
    g_target_hwnd = FindCurrentProcessMainWindow();
  }

  if (g_target_hwnd == nullptr || !g_vk_ctx.ready ||
      g_vk_ctx.instance == VK_NULL_HANDLE ||
      g_vk_ctx.physical_device == VK_NULL_HANDLE ||
      g_vk_ctx.device == VK_NULL_HANDLE ||
      g_vk_ctx.queue == VK_NULL_HANDLE ||
      g_vk_ctx.descriptor_pool == VK_NULL_HANDLE ||
      g_vk_ctx.render_pass == VK_NULL_HANDLE) {
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
  (void)draw_data;
  (void)queue;
  (void)pPresentInfo;
  // Conecta aquí la grabación y envío de tu VkCommandBuffer antes de presentar:
  // ImGui_ImplVulkan_RenderDrawData(draw_data, cmd_buffer);
}

VkResult VKAPI_PTR Hooked_vkQueuePresentKHR(VkQueue queue,
                                           const VkPresentInfoKHR* pPresentInfo) {
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

bool InstallVulkanPresentHook() {
  HMODULE vk_mod = GetModuleHandleA("vulkan-1.dll");
  if (vk_mod == nullptr) {
    return false;
  }

  auto present_addr =
      reinterpret_cast<void*>(GetProcAddress(vk_mod, "vkQueuePresentKHR"));
  if (present_addr == nullptr) {
    return false;
  }

  if (MH_Initialize() != MH_OK) {
    return false;
  }

  if (MH_CreateHook(present_addr,
                    reinterpret_cast<void*>(&Hooked_vkQueuePresentKHR),
                    reinterpret_cast<void**>(&g_orig_vkQueuePresentKHR)) !=
      MH_OK) {
    MH_Uninitialize();
    return false;
  }

  if (MH_EnableHook(present_addr) != MH_OK) {
    MH_Uninitialize();
    return false;
  }

  return true;
}

void ShutdownImGuiIfInitialized() {
  if (g_imgui_initialized) {
    ImGui_ImplVulkan_Shutdown();
    ImGui_ImplWin32_Shutdown();
    ImGui::DestroyContext();
    g_imgui_initialized = false;
  }
}

DWORD WINAPI OverlayWorkerThread(LPVOID) {
  g_worker_active.store(true);
  g_gc_listener.Start();

  while (g_worker_active.load()) {
    if (InstallVulkanPresentHook()) {
      break;
    }
    Sleep(100);
  }

  while (g_worker_active.load()) {
    Sleep(50);
  }

  ShutdownImGuiIfInitialized();
  MH_DisableHook(MH_ALL_HOOKS);
  MH_Uninitialize();
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
      MH_DisableHook(MH_ALL_HOOKS);
      MH_Uninitialize();
      g_gc_listener.Stop();
      break;
  }
  return TRUE;
}