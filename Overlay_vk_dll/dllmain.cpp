#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <atomic>
#include <cstdint>

#include "udp_gc_listener.h"

namespace {

UdpGcListener g_gc_listener(49152, 49153);
std::atomic<bool> g_worker_active{false};
HANDLE g_init_thread = nullptr;

DWORD WINAPI OverlayWorkerThread(LPVOID) {
  g_worker_active.store(true);
  g_gc_listener.Start();

  while (g_worker_active.load()) {
    // Aquí irá en el siguiente paso la instalación del hook de Vulkan (vkQueuePresentKHR)
    // y la actualización del estado para Dear ImGui usando ReadGcOverlayState(1 / 2).
    Sleep(50);
  }

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