import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource-variable/source-serif-4/opsz.css";
import "@fontsource-variable/source-serif-4/opsz-italic.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "katex/dist/katex.min.css";
import "./styles/index.css";
import App from "./app/App";
import { applyTheme, DEFAULT_ACCENT } from "./app/theme";

// 先按默认值写入令牌，启动页不会闪白
applyTheme(DEFAULT_ACCENT, "system", "standard");

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
