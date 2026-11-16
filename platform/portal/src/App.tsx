import { Navigate, Route, Routes } from "react-router-dom";
import { RequireAuth } from "./auth";
import { AppShell, PublicLayout } from "./Layout";
import { AgentReports } from "./pages/AgentReports";
import { Areas } from "./pages/Areas";
import { OpsRoot, RequireOps } from "./opsAuth";
import { OpsActivity } from "./pages/ops/OpsActivity";
import { OpsLayout } from "./pages/ops/OpsLayout";
import { OpsLogin } from "./pages/ops/OpsLogin";
import { OpsOrganizations } from "./pages/ops/OpsOrganizations";
import { OpsOrgDetail } from "./pages/ops/OpsOrgDetail";
import { AdminActivity } from "./pages/admin/AdminActivity";
import { AdminAgentDetail } from "./pages/admin/AdminAgentDetail";
import { AdminAgents } from "./pages/admin/AdminAgents";
import { AdminAreas } from "./pages/admin/AdminAreas";
import { AdminUsers } from "./pages/admin/AdminUsers";
import { Downloads } from "./pages/Downloads";
import { Landing } from "./pages/Landing";
import { Login } from "./pages/Login";
import { NotFound } from "./pages/NotFound";
import { ReportView } from "./pages/ReportView";

/** Administration pages: org_admin only (anyone else is sent back to /app). */
function Admin({ children }: { children: React.ReactNode }) {
  return <RequireAuth admin>{children}</RequireAuth>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      {/* Operator console: not linked from anywhere; looks like an unknown page when the server has it off. */}
      <Route path="/ops" element={<OpsRoot />}>
        <Route index element={<Navigate to="/ops/organizations" replace />} />
        <Route path="login" element={<OpsLogin />} />
        <Route element={<RequireOps><OpsLayout /></RequireOps>}>
          <Route path="organizations" element={<OpsOrganizations />} />
          <Route path="organizations/:orgId" element={<OpsOrgDetail />} />
          <Route path="activity" element={<OpsActivity />} />
        </Route>
        <Route path="*" element={<Navigate to="/ops/organizations" replace />} />
      </Route>
      <Route element={<PublicLayout />}>
        <Route path="/" element={<Landing />} />
        <Route path="*" element={<NotFound />} />
      </Route>
      <Route path="/app" element={<AppShell />}>
        <Route index element={<Areas />} />
        <Route path="areas/:areaId" element={<Areas />} />
        <Route path="areas/:areaId/agents/:agentId" element={<AgentReports />} />
        <Route path="reports/:reportId" element={<ReportView />} />
        <Route path="downloads" element={<Downloads />} />
        <Route path="admin/downloads" element={<Admin><Downloads admin /></Admin>} />
        <Route path="admin/areas" element={<Admin><AdminAreas /></Admin>} />
        <Route path="admin/agents" element={<Admin><AdminAgents /></Admin>} />
        <Route path="admin/agents/:agentId" element={<Admin><AdminAgentDetail /></Admin>} />
        <Route path="admin/users" element={<Admin><AdminUsers /></Admin>} />
        <Route path="admin/activity" element={<Admin><AdminActivity /></Admin>} />
        <Route path="*" element={<Navigate to="/app" replace />} />
      </Route>
    </Routes>
  );
}
