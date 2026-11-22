// Setup mode: the keychain opens its own Wi-Fi network with a small page where the phone
// chooses the home network, and receives the favourite stations from the à point app
// (the app's "Envoyer au porte-clés" opens http://192.168.4.1/f?ids=...).
// Nothing goes through a server.
#pragma once
#include <Arduino.h>

namespace portal {

void begin();  // starts the access point, DNS (captive page) and web server
void loop();
void end();

String ssid();
String password();
String qrText();         // WIFI:T:WPA;S:...;P:...;; for the phone camera
bool changed();          // true once after Wi-Fi or favourites were received
bool doneRequested();    // the page's "Terminer" was pressed
int favouritesReceived();
int wifiStatus();  // 0 not tested, 1 testing, 2 joined, 3 failed

}  // namespace portal
