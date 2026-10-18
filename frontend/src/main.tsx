import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import Landing from "./pages/Landing";
import Auth from "./pages/Auth";
import Dashboard from "./pages/Dashboard";
import NewSession from "./pages/NewSession";
import Chat from "./pages/Chat";
import ReportView from "./pages/ReportView";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/auth" element={<Auth />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/new" element={<NewSession />} />
        <Route path="/chat/:sessionId" element={<Chat />} />
        <Route path="/report/:reportId" element={<ReportView />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
);
