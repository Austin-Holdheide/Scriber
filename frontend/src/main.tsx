import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import GlobalSearchProvider from "./components/GlobalSearch";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <GlobalSearchProvider><BrowserRouter><App /></BrowserRouter></GlobalSearchProvider>
  </React.StrictMode>
);
