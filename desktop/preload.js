const { contextBridge, ipcRenderer } = require("electron");

// API base URL for the dashboard (passed as ?api=... by the main process).
const api = new URLSearchParams(location.search).get("api");
if (api) contextBridge.exposeInMainWorld("GB_API", api);

contextBridge.exposeInMainWorld("wizard", {
  systemCheck: () => ipcRenderer.invoke("wizard:systemCheck"),
  installEngine: (pythonExe) => ipcRenderer.invoke("wizard:installEngine", { pythonExe }),
  finish: (cfg) => ipcRenderer.invoke("wizard:finish", cfg),
  openExternal: (url) => ipcRenderer.invoke("wizard:openExternal", url),
  onLog: (fn) => ipcRenderer.on("wizard:log", (_e, line) => fn(line)),
});
