import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "@/app/App";
import "@/index.css";

const container = document.getElementById("root");
if (!container) throw new Error("Элемент #root не найден");

ReactDOM.createRoot(container).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
