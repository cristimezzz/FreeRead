import React from "react";
import ReactDOM from "react-dom/client";
import "katex/dist/katex.min.css";
import "./styles/global.css";
import "./components/md";
import App from "./app/App";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
