#pragma once

#include <cstdint>

#include "params.hpp"

namespace msg {

// Internal sim <-> fsw bus. Sent as raw structs in host byte order because both
// ends run on the same machine. Layouts are listed in docs/icd.md.
struct SensorPacket {
  uint32_t seq;
  uint32_t sun_present;
  double time_s;
  double battery_V;
  double battery_A;  // positive = charging
  double array_A;
  double thermistor_K[params::kNumNodes];
};
static_assert(sizeof(SensorPacket) == 80, "SensorPacket layout changed; update docs/icd.md");

struct ActuatorPacket {
  uint32_t seq;  // echoes the SensorPacket it answers
  uint8_t heater_on;
  uint8_t payload_on;
  uint8_t spare[2];
};
static_assert(sizeof(ActuatorPacket) == 8, "ActuatorPacket layout changed; update docs/icd.md");

// Enumerations carried in CCSDS packets to and from the ground.
enum class Mode : uint8_t { kNominal = 0, kLoadShed = 1, kSafe = 2 };
enum class Opcode : uint8_t {
  kNoop = 0,
  kSetMode = 1,
  kPayloadOn = 2,
  kPayloadOff = 3,
  kSetHeaterSetpoints = 4,
};
enum class EventType : uint8_t {
  kModeChange = 1,
  kCmdAck = 2,
  kCmdNack = 3,
  kBatteryDegraded = 4,
  kRadiatorDegraded = 5,
};
enum class ModeReason : uint8_t {
  kSocLow = 1,
  kSocCritical = 2,
  kRedLimit = 3,
  kGroundCommand = 4,
  kSocRecovered = 5,
};
enum class NackReason : uint8_t {
  kNone = 0,  // accepted
  kMalformed = 1,
  kUnknownOpcode = 2,
  kBadLength = 3,
  kBadArgument = 4,
  kWrongMode = 5,
};

}  // namespace msg
