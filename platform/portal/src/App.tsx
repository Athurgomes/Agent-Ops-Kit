import { Navigate, Route, Routes } from "react-router-dom";
import { RequireAuth } from "./auth";
import { AppShell, PublicLayout } from "./Layout";
import { AgentReports } from "./pages/AgentReports";
import { Areas } from "./pages/Areas";
import { Downloads } from "./pages/Downloads";
import { Landing } from "./pages/Landing";
import { Login } from "./pages/Login";
import { NotFound } from "./pages/NotFound";
import { ReportView } from "./pages/ReportView";

export default function App() {
  return (
    <Routes>
      <Route element={<PublicLayout />}>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<NotFound />} />
      </Route>
      <Route path="/app" element={<AppShell />}>
        <Route index element={<Areas />} />
        <Route path="areas/:areaId" element={<Areas />} />
        <Route path="areas/:areaId/agents/:agentId" element={<AgentReports />} />
        <Route path="reports/:reportId" element={<ReportView />} />
        <Route path="downloads" element={<Downloads />} />
        <Route
          path="admin/downloads"
          element={
            <RequireAuth admin>
              <Downloads admin />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/app" replace />} />
      </Route>
    </Routes>
  );
}
