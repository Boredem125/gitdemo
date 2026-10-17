import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { Home } from "./pages/Home";
import { MatchPage } from "./pages/MatchPage";
import { StreamPage } from "./pages/StreamPage";
import { TeamPage } from "./pages/TeamPage";
import "./styles.css";

function App() {
  return (
    <BrowserRouter>
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="logo">◎</span> BGMI Analyzer
        </Link>
      </header>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/streams/:id" element={<StreamPage />} />
        <Route path="/matches/:id" element={<MatchPage />} />
        <Route path="/teams/:tag" element={<TeamPage />} />
      </Routes>
    </BrowserRouter>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
