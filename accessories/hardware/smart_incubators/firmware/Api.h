// Api.h
// HTTP REST server on port 80. The node discovers the unit on two channels and polls these.
//   Incubator API (IncubatorScanner):
//     GET  /telemetry   live readings + state (JSON)
//     GET  /config      current persisted config (JSON)
//     POST /config      update a subset of config fields (JSON body) → persist
//     POST /command     transient actions: sync_time, identify, reboot, set_light (JSON)
//     GET  /health      diagnostics: wifi, heap, time, sensor fault flags (JSON)
//   Sensor API (SensorScanner — identical to accessories/hardware/etho_sensor):
//     GET  /            sensor JSON {id, ip, name, location, temperature, humidity, light}
//     GET  /id          {"id":"<MAC>"}
//     POST /set         update sensor name/location (JSON body)
//   GET  /status        human-readable status page
#pragma once

namespace Api {
  void begin();    // register routes and start the server
  void update();   // service incoming HTTP requests (call often)
}
