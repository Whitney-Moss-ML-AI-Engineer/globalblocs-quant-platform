// Native settings Capacitor doesn't generate on its own. Safe to run repeatedly.
// Native HTTP (CapacitorHttp) carries API calls, so the only extra need is permission to reach a
// desktop on the home network over plain HTTP. Cloud servers should use HTTPS.
const fs = require("fs"), path = require("path");
const root = path.join(__dirname, "..");
const target = process.argv[2];

if (target === "android") {
  const resXml = path.join(root, "android/app/src/main/res/xml");
  fs.mkdirSync(resXml, { recursive: true });
  fs.writeFileSync(path.join(resXml, "network_security_config.xml"),
`<?xml version="1.0" encoding="utf-8"?>
<!-- HTTPS everywhere, except plain HTTP so the app can reach the paired GlobalBLOCS desktop on home Wi-Fi. -->
<network-security-config>
  <base-config cleartextTrafficPermitted="true">
    <trust-anchors><certificates src="system" /></trust-anchors>
  </base-config>
</network-security-config>
`);
  const manifest = path.join(root, "android/app/src/main/AndroidManifest.xml");
  let m = fs.readFileSync(manifest, "utf8");
  if (!m.includes("networkSecurityConfig")) {
    m = m.replace("<application", '<application\n        android:networkSecurityConfig="@xml/network_security_config"');
  }
  if (!m.includes("android.permission.ACCESS_NETWORK_STATE")) {
    m = m.replace("</manifest>", '    <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />\n</manifest>');
  }
  fs.writeFileSync(manifest, m);
  console.log("Android configured: home-network HTTP allowed via network_security_config.xml");
}

if (target === "ios") {
  const plist = path.join(root, "ios/App/App/Info.plist");
  let p = fs.readFileSync(plist, "utf8");
  if (!p.includes("NSAppTransportSecurity")) {
    p = p.replace(/<dict>/, `<dict>
	<key>NSAppTransportSecurity</key>
	<dict>
		<key>NSAllowsLocalNetworking</key>
		<true/>
	</dict>
	<key>NSLocalNetworkUsageDescription</key>
	<string>GlobalBLOCS connects to your GlobalBLOCS desktop app on your home Wi-Fi to show your research and portfolio.</string>`);
  }
  fs.writeFileSync(plist, p);
  console.log("iOS configured: local-network access + usage description added to Info.plist");
}
