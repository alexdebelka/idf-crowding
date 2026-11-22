#include "portal.h"

#include <DNSServer.h>
#include <WebServer.h>
#include <WiFi.h>

#include "config.h"
#include "src/stations_data.h"
#include "store.h"

namespace portal {

static WebServer server(80);
static DNSServer dns;
static String apSsid, apPass, scanOptions;
static bool dirty = false, done = false;
static int wifiState = 0;  // 0 not tested, 1 testing, 2 joined, 3 failed
static uint32_t testStart = 0;

String ssid() { return apSsid; }
String password() { return apPass; }
bool changed() {
  bool d = dirty;
  dirty = false;
  return d;
}
bool doneRequested() { return done; }
int favouritesReceived() {
  String ids[MAX_FAVS];
  return store::favourites(ids);
}

static String esc(const String &s) {
  String o;
  for (size_t i = 0; i < s.length(); i++) {
    char c = s[i];
    if (c == '&') o += "&amp;";
    else if (c == '<') o += "&lt;";
    else if (c == '>') o += "&gt;";
    else if (c == '"') o += "&quot;";
    else o += c;
  }
  return o;
}

static String qrEsc(const String &s) {
  String o;
  for (size_t i = 0; i < s.length(); i++) {
    char c = s[i];
    if (c == '\\' || c == ';' || c == ',' || c == ':' || c == '"') o += '\\';
    o += c;
  }
  return o;
}

String qrText() { return "WIFI:T:WPA;S:" + qrEsc(apSsid) + ";P:" + qrEsc(apPass) + ";;"; }

static const char HEAD[] PROGMEM =
    "<!doctype html><html lang=fr><head><meta charset=utf-8>"
    "<meta name=viewport content='width=device-width,initial-scale=1'><title>à point · porte-clés</title>"
    "<style>body{margin:0;font:16px/1.4 system-ui,sans-serif;background:#F6F7F4;color:#0E1116}"
    "main{max-width:420px;margin:0 auto;padding:24px 20px}h1{font-size:30px;margin:0 0 4px}"
    "h2{font-size:19px;margin:28px 0 8px}p{margin:8px 0}.ok{background:#D9F84A;border-radius:12px;"
    "padding:10px 14px}label{display:block;font-weight:600;margin:12px 0 4px}select,input{width:100%;"
    "box-sizing:border-box;font:inherit;padding:12px;border:1px solid #0E1116;border-radius:10px;"
    "background:#fff}button,.btn{display:block;width:100%;box-sizing:border-box;margin-top:16px;"
    "padding:14px;border:0;border-radius:999px;background:#0E1116;color:#F6F7F4;font:inherit;"
    "font-weight:700;text-align:center;text-decoration:none}small{color:#4A5466}"
    "ul,ol{list-style:none;margin:8px 0;padding:0}li{display:flex;align-items:center;gap:8px;"
    "padding:10px 12px;margin:6px 0;background:#fff;border:1px solid #D5DAE1;border-radius:10px}"
    "li span{flex:1}li b{font-weight:700}li em{font-style:normal;color:#4A5466;font-size:14px}"
    "li button{width:auto;margin:0;padding:8px 12px;font-size:14px}"
    "li button.x{background:#fff;color:#0E1116;border:1px solid #0E1116}</style></head><body><main>";
static const char TAIL[] PROGMEM = "</main></body></html>";

static void page(const String &body, int code = 200) {
  server.sendHeader("Cache-Control", "no-store");
  server.send(code, "text/html; charset=utf-8", String(FPSTR(HEAD)) + body + FPSTR(TAIL));
}

static String status() {
  String s;
  String w = store::wifiSsid();
  int n = favouritesReceived();
  const char *test = wifiState == 2 ? " (connexion réussie)" : wifiState == 3 ? " (échec : vérifiez le mot de passe, réseau 2,4 GHz)" : "";
  s += "<p class=ok>Wi-Fi : " + (w.length() ? "<b>" + esc(w) + "</b>" + test : String("pas encore choisi")) +
       "<br>Gares : <b>" + String(n) + "</b></p>";
  return s;
}

static void handleRoot() {
  String b = "<h1>à point</h1><p>Réglages du porte-clés.</p>" + status();
  b += "<h2>1. Wi-Fi</h2><p><small>Le réseau que le porte-clés utilisera chaque jour pour mettre à jour "
       "les prévisions (box ou partage de connexion).</small></p><form method=post action=/wifi>"
       "<label for=s>Réseau</label><select id=s name=s>" +
       scanOptions +
       "</select><label for=o>Ou son nom</label><input id=o name=o autocomplete=off>"
       "<label for=p>Mot de passe</label><input id=p name=p type=password autocomplete=off>"
       "<button>Enregistrer</button></form>";
  // Station picker: works on the keychain's own network, without Internet (list in src/stations_data.h).
  String favs;
  {
    String ids[MAX_FAVS];
    int n = store::favourites(ids);
    for (int i = 0; i < n; i++) favs += (i ? "," : "") + ids[i];
  }
  b += "<h2>2. Vos gares</h2><p><small>Jusqu’à 12, dans l’ordre où le porte-clés les montre. Chaque ajout est enregistré.</small></p>"
       "<ol id=c></ol><label for=q>Ajouter une gare</label><input id=q type=search autocomplete=off "
       "placeholder='Châtelet, Nation…'><ul id=r></ul><p id=st><small></small></p>"
       "<script src=/stations.js></script><script>"
       "const F='" + favs + "'.split(',').filter(x=>x);"
       "const by=Object.fromEntries(S.map(s=>[s[0],s]));let C=F.filter(i=>by[i]);"
       "const n=t=>t.normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();"
       "const N=S.map(s=>n(s[1]));const q=document.getElementById('q'),r=document.getElementById('r'),"
       "c=document.getElementById('c');"
       "function item(s,btn,cls,fn){const li=document.createElement('li');const sp=document.createElement('span');"
       "const nb=document.createElement('b');nb.textContent=s[1];const em=document.createElement('em');"
       "em.textContent=' '+s[2];sp.append(nb,em);const bt=document.createElement('button');bt.type='button';"
       "bt.textContent=btn;if(cls)bt.className=cls;bt.onclick=fn;li.append(sp,bt);return li}"
       "const st=document.querySelector('#st small');"
       "function save(){if(!C.length){st.textContent='Ajoutez au moins une gare.';return}"
       "st.textContent='Enregistrement…';fetch('/f?quiet=1&ids='+C.join(',')).then(r=>{st.textContent="
       "r.ok?'Enregistré sur le porte-clés ('+C.length+').':'Pas enregistré, réessayez.'}).catch(()=>{"
       "st.textContent='Pas enregistré : rejoignez le réseau du porte-clés.'})}"
       "function draw(){c.replaceChildren(...C.map((id,i)=>item(by[id],'Retirer','x',()=>{C.splice(i,1);draw();find();save()})));"
       "if(!C.length){const li=document.createElement('li');li.textContent='Aucune gare pour l’instant.';c.append(li)}}"
       "function find(){const t=n(q.value);r.replaceChildren();if(t.length<2)return;const m=[];"
       "for(let i=0;i<S.length;i++){const p=N[i].indexOf(t);if(p<0||C.includes(S[i][0]))continue;"
       "m.push([p==0?0:N[i][p-1]==' '?1:2,i])}m.sort((a,b)=>a[0]-b[0]||a[1]-b[1]);"
       "for(const[,i]of m.slice(0,8))r.append(item(S[i],'Ajouter','',()=>{if(C.length>=12)"
       "{alert('12 gares au plus.');return}C.push(S[i][0]);q.value='';find();draw();save()}))}"
       "q.oninput=find;draw();"
       "</script>";
  b += "<h2>3. Terminer</h2><a class=btn href=/done>Terminer</a>";
  page(b);
}

int wifiStatus() { return wifiState; }

static void handleWifi() {
  String s = server.arg("o");
  s.trim();
  if (!s.length()) s = server.arg("s");
  String p = server.arg("p");
  if (!s.length() || s.length() > 32 || p.length() > 63) {
    page("<h1>Oups.</h1><p>Choisissez un réseau.</p><a class=btn href=/>Retour</a>", 400);
    return;
  }
  store::setWifi(s, p);
  // The test runs after this answer: joining a network can move the access point to that
  // network's channel, and the phone may drop off for a moment.
  wifiState = 1;
  testStart = millis();
  dirty = true;
  page("<h1>C’est noté.</h1><p>Le porte-clés essaie de rejoindre <b>" + esc(s) +
       "</b> ; le résultat s’affiche sur son écran. Si ce téléphone quitte le réseau du porte-clés, "
       "rejoignez-le à nouveau.</p><a class=btn href=/>Continuer</a>");
  WiFi.begin(s.c_str(), p.c_str());
}

static void handleFavourites() {
  int n = store::setFavourites(server.arg("ids"));
  if (server.hasArg("quiet")) {  // saved from the setup page's station picker, as it changes
    if (n) dirty = true;
    server.sendHeader("Cache-Control", "no-store");
    server.send(n ? 204 : 400, "text/plain", "");
    return;
  }
  if (!n) {
    page("<h1>Aucune gare reçue.</h1><p>Marquez des gares d’une étoile dans l’app, puis renvoyez-les.</p>", 400);
    return;
  }
  dirty = true;
  page("<h1>" + String(n) + (n > 1 ? " gares reçues." : " gare reçue.") + "</h1>" + status() +
       "<a class=btn href=/done>Terminer</a><a class=btn href=/ style='background:#fff;color:#0E1116;"
       "border:1px solid #0E1116'>Modifier</a>");
}

static void handleDone() {
  if (!store::wifiSsid().length()) {
    page("<h1>Encore une étape.</h1><p>Choisissez d’abord le Wi-Fi.</p><a class=btn href=/>Retour</a>");
    return;
  }
  if (!favouritesReceived()) {
    page("<h1>Encore une étape.</h1><p>Ajoutez au moins une gare.</p><a class=btn href=/>Retour</a>");
    return;
  }
  page("<h1>C’est prêt.</h1><p>Le porte-clés redémarre et télécharge vos gares. Vous pouvez quitter ce "
       "réseau.</p>");
  done = true;
}

static void captive() {
  server.sendHeader("Location", String("http://") + AP_IP + "/", true);
  server.send(302, "text/plain", "");
}

static void scan() {
  int n = WiFi.scanNetworks();
  scanOptions = "";
  String saved = store::wifiSsid();
  for (int i = 0; i < n && i < 20; i++) {
    String s = WiFi.SSID(i);
    if (!s.length() || scanOptions.indexOf(">" + esc(s) + "<") >= 0) continue;
    scanOptions += "<option" + String(s == saved ? " selected" : "") + ">" + esc(s) + "</option>";
  }
  WiFi.scanDelete();
}

void begin() {
  uint64_t mac = ESP.getEfuseMac();
  char suffix[5];
  snprintf(suffix, sizeof suffix, "%04X", (unsigned)((mac >> 32) & 0xFFFF));
  apSsid = String(AP_SSID_PREFIX) + suffix;
  apPass = store::apPassword();
  done = false;
  wifiState = 0;
  WiFi.mode(WIFI_AP_STA);
  scan();
  IPAddress ip;
  ip.fromString(AP_IP);
  WiFi.softAPConfig(ip, ip, IPAddress(255, 255, 255, 0));
  WiFi.softAP(apSsid.c_str(), apPass.c_str());
  dns.start(53, "*", ip);
  server.on("/", HTTP_GET, handleRoot);
  server.on("/wifi", HTTP_POST, handleWifi);
  server.on("/f", HTTP_GET, handleFavourites);
  server.on("/done", HTTP_GET, handleDone);
  server.on("/stations.js", HTTP_GET, [] {
    server.sendHeader("Cache-Control", "max-age=3600");
    server.send_P(200, "application/javascript; charset=utf-8", STATIONS_JS);
  });
  server.onNotFound(captive);
  server.begin();
}

void loop() {
  dns.processNextRequest();
  server.handleClient();
  if (wifiState == 1) {
    if (WiFi.status() == WL_CONNECTED) {
      wifiState = 2;
      dirty = true;
      WiFi.disconnect(false);
    } else if (millis() - testStart > 12000) {
      wifiState = 3;
      dirty = true;
      WiFi.disconnect(false);
    }
  }
}

void end() {
  server.stop();
  dns.stop();
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_OFF);
}

}  // namespace portal
