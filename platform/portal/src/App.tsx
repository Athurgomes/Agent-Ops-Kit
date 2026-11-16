import { Navigate, Route, Routes } from "react-router-dom";
import { CatalogProvider, RequireAuth } from "./auth";
import { Layout } from "./Layout";
import { AgentReports } from "./pages/AgentReports";
import { Areas } from "./pages/Areas";
import { Downloads } from "./pages/Downloads";
import { Landing } from "./pages/Landing";
import { Login } from "./pages/Login";
import { NotFound } from "./pages/NotFound";
import { ReportView } from "./pages/ReportView";

/** Tudo em /app exige sessão; o catálogo (áreas e agentes) é carregado uma vez por login. */
function Private({ admin = false, children }: { admin?: boolean; children: React.ReactNode }) {
  return (
    <RequireAuth admin={admin}>
      <CatalogProvider>{children}</CatalogProvider>
    </RequireAuth>
  );
}

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/entrar" element={<Login />} />
        <Route path="/app" element={<Private><Areas /></Private>} />
        <Route path="/app/areas/:areaId" element={<Private><Areas /></Private>} />
        <Route
          path="/app/areas/:areaId/agentes/:agentId"
          element={<Private><AgentReports /></Private>}
        />
        <Route path="/app/relatorios/:reportId" element={<Private><ReportView /></Private>} />
        <Route path="/app/downloads" element={<Private><Downloads /></Private>} />
        <Route
          path="/app/admin/downloads"
          element={<Private admin><Downloads admin /></Private>}
        />
        <Route path="/app/*" element={<Navigate to="/app" replace />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Layout>
  );
}
