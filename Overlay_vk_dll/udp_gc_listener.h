#pragma once

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif

#include <winsock2.h>
#include <ws2tcpip.h>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

struct GcPadState {
  int status = 0;
  std::vector<std::string> botones;
  int stick_x = 128;
  int stick_y = 128;
  int c_stick_x = 128;
  int c_stick_y = 128;
  int l_analog = 0;
  int r_analog = 0;
  bool connected = false;
  std::chrono::steady_clock::time_point last_update{};
};

class UdpGcListener {
 public:
  UdpGcListener(uint16_t port_p1 = 49152, uint16_t port_p2 = 49153)
      : port_p1_(port_p1), port_p2_(port_p2) {}

  ~UdpGcListener() { Stop(); }

  bool Start() {
    if (running_.exchange(true)) {
      return true;
    }

    WSADATA wsa_data{};
    if (WSAStartup(MAKEWORD(2, 2), &wsa_data) != 0) {
      running_.store(false);
      return false;
    }

    sock_p1_ = CreateBoundSocket(port_p1_);
    sock_p2_ = CreateBoundSocket(port_p2_);
    if (sock_p1_ == INVALID_SOCKET || sock_p2_ == INVALID_SOCKET) {
      Stop();
      return false;
    }

    worker_ = std::thread(&UdpGcListener::WorkerLoop, this);
    return true;
  }

  void Stop() {
    running_.store(false);
    CloseSocket(sock_p1_);
    CloseSocket(sock_p2_);
    if (worker_.joinable()) {
      worker_.join();
    }
    WSACleanup();
  }

  GcPadState GetPlayerState(int player) const {
    std::lock_guard<std::mutex> lock(mtx_);
    return (player == 2) ? p2_ : p1_;
  }

 private:
  static SOCKET CreateBoundSocket(uint16_t port) {
    SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s == INVALID_SOCKET) {
      return INVALID_SOCKET;
    }

    u_long non_blocking = 1;
    ioctlsocket(s, FIONBIO, &non_blocking);

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

    if (bind(s, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) ==
        SOCKET_ERROR) {
      closesocket(s);
      return INVALID_SOCKET;
    }
    return s;
  }

  static void CloseSocket(SOCKET& s) {
    if (s != INVALID_SOCKET) {
      closesocket(s);
      s = INVALID_SOCKET;
    }
  }

  static int ExtractIntField(const std::string& json, const std::string& key,
                             int fallback) {
    const std::string pat = "\"" + key + "\"";
    auto pos = json.find(pat);
    if (pos == std::string::npos) return fallback;
    pos = json.find(':', pos + pat.size());
    if (pos == std::string::npos) return fallback;
    pos = json.find_first_of("-0123456789", pos + 1);
    if (pos == std::string::npos) return fallback;
    try {
      return std::stoi(json.substr(pos));
    } catch (...) {
      return fallback;
    }
  }

  static void ExtractPairField(const std::string& json, const std::string& key,
                               int& out_x, int& out_y) {
    const std::string pat = "\"" + key + "\"";
    auto pos = json.find(pat);
    if (pos == std::string::npos) return;
    auto lb = json.find('[', pos + pat.size());
    auto rb = (lb == std::string::npos) ? std::string::npos : json.find(']', lb);
    if (lb == std::string::npos || rb == std::string::npos) return;
    std::string inside = json.substr(lb + 1, rb - lb - 1);
    auto comma = inside.find(',');
    try {
      if (comma != std::string::npos) {
        out_x = std::stoi(inside.substr(0, comma));
        out_y = std::stoi(inside.substr(comma + 1));
      }
    } catch (...) {
    }
  }

  static std::vector<std::string> ExtractButtons(const std::string& json) {
    std::vector<std::string> result;
    const std::string pat = "\"botones\"";
    auto pos = json.find(pat);
    if (pos == std::string::npos) return result;
    auto lb = json.find('[', pos + pat.size());
    auto rb = (lb == std::string::npos) ? std::string::npos : json.find(']', lb);
    if (lb == std::string::npos || rb == std::string::npos) return result;

    size_t cur = lb + 1;
    while (cur < rb) {
      auto q1 = json.find('"', cur);
      if (q1 == std::string::npos || q1 >= rb) break;
      auto q2 = json.find('"', q1 + 1);
      if (q2 == std::string::npos || q2 > rb) break;
      result.push_back(json.substr(q1 + 1, q2 - q1 - 1));
      cur = q2 + 1;
    }
    return result;
  }

  void PollSocket(SOCKET s, int default_player) {
    if (s == INVALID_SOCKET) return;
    char buf[4096];
    std::string last_payload;
    while (true) {
      int n = recvfrom(s, buf, sizeof(buf) - 1, 0, nullptr, nullptr);
      if (n <= 0) {
        break;
      }
      buf[n] = '\0';
      last_payload.assign(buf, static_cast<size_t>(n));
    }

    if (last_payload.empty()) {
      return;
    }

    GcPadState parsed;
    parsed.status = ExtractIntField(last_payload, "status", 0);
    parsed.botones = ExtractButtons(last_payload);
    ExtractPairField(last_payload, "stick", parsed.stick_x, parsed.stick_y);
    ExtractPairField(last_payload, "c_stick", parsed.c_stick_x,
                     parsed.c_stick_y);
    parsed.l_analog = ExtractIntField(last_payload, "l_analog", 0);
    parsed.r_analog = ExtractIntField(last_payload, "r_analog", 0);
    parsed.connected = (parsed.status != 0) || !parsed.botones.empty() ||
                       parsed.stick_x != 128 || parsed.stick_y != 128;
    parsed.last_update = std::chrono::steady_clock::now();

    int player = ExtractIntField(last_payload, "player", default_player);
    std::lock_guard<std::mutex> lock(mtx_);
    if (player == 2) {
      p2_ = std::move(parsed);
    } else {
      p1_ = std::move(parsed);
    }
  }

  void WorkerLoop() {
    while (running_.load()) {
      PollSocket(sock_p1_, 1);
      PollSocket(sock_p2_, 2);
      std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
  }

  uint16_t port_p1_;
  uint16_t port_p2_;
  SOCKET sock_p1_ = INVALID_SOCKET;
  SOCKET sock_p2_ = INVALID_SOCKET;
  std::atomic<bool> running_{false};
  std::thread worker_;
  mutable std::mutex mtx_;
  GcPadState p1_;
  GcPadState p2_;
};