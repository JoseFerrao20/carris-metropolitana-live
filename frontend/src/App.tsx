import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { LoginPage } from "./pages/LoginPage";

// O mapa (maplibre-gl, ~800 kB) só é descarregado quando se abre a página do mapa.
const LivePage = lazy(() => import("./pages/LivePage").then((m) => ({ default: m.LivePage })));

export function App() {
  return (
    <Routes>
      <Route
        path="/"
        element={
          <Suspense fallback={<p className="muted center">A carregar o mapa…</p>}>
            <LivePage />
          </Suspense>
        }
      />
      <Route path="/analytics" element={<AnalyticsPage />} />
      <Route path="/entrar" element={<LoginPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
