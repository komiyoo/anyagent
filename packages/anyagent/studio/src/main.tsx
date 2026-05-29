import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { StudioApp } from "./StudioApp";
import "@heroui/styles/css";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <HashRouter>
      <StudioApp />
    </HashRouter>
  </React.StrictMode>,
);
