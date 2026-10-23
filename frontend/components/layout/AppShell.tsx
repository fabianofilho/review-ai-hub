/**
 * The one authenticated shell: Topbar + sidebar + mobile drawer around every
 * shell route (`/`, `/projects/:projectId`, `/settings`).
 *
 * It derives everything from the URL and deliberately does NOT consume
 * ProjectContext — ProjectProvider writes `?tab=` in a mount effect and stays
 * wrapping ProjectView alone (spec §3.1). It owns `switcherOpen` so `G P` no
 * longer closes over state that only exists inside a project route (ledger
 * discrepancy D).
 *
 * `data-project-id` renders the derivation so route tests can assert their
 * precondition rather than inferring it from absent markup.
 */
import React, {useState} from 'react';
import {Outlet} from 'react-router';
import {Topbar} from '@/components/navigation';
import {ProjectSidebar} from './ProjectSidebar';
import {MobileSidebar} from './MobileSidebar';
import {useSidebar} from '@/contexts/SidebarContext';
import {HeaderActionsProvider} from '@/contexts/HeaderActionsContext';
import {useShellLocation} from '@/hooks/useShellLocation';
import {useProjectsQuery} from '@/hooks/useProjectsQuery';
import {useNavigationShortcuts} from '@/hooks/useNavigationShortcuts';

export const AppShell: React.FC = () => {
  const {projectId, activeSection} = useShellLocation();
  const {toggleSidebar, mobileOpen, setMobileOpen} = useSidebar();
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const {data: projects} = useProjectsQuery();

  useNavigationShortcuts({
    projectId,
    onToggleSidebar: toggleSidebar,
    onOpenProjectSwitcher: () => setSwitcherOpen(true),
  });

  // The project name comes from the shared list cache, not ProjectContext, and
  // not a second read: the switcher mounts the same query.
  const projectName = projectId === null
    ? undefined
    : projects?.find((project) => project.id === projectId)?.name;

  return (
    <HeaderActionsProvider>
      <div
        data-testid="app-shell"
        data-project-id={projectId ?? ''}
        className="relative flex h-screen flex-col overflow-hidden bg-background"
      >
        <div className="shrink-0">
          <Topbar />
        </div>

        <MobileSidebar
          open={mobileOpen}
          onOpenChange={setMobileOpen}
          projectId={projectId}
          activeTab={activeSection ?? ''}
          projectName={projectName}
        />

        <div className="flex flex-1 overflow-hidden">
          <ProjectSidebar
            projectId={projectId}
            activeTab={activeSection ?? ''}
            projectName={projectName}
            switcherOpen={switcherOpen}
            onSwitcherOpenChange={setSwitcherOpen}
          />
          <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
            <Outlet />
          </main>
        </div>
      </div>
    </HeaderActionsProvider>
  );
};
