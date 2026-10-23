/**
 * One shell wraps `/`, `/settings` and `/projects/:projectId` (spec §3).
 *
 * The no-project assertions carry their PRECONDITION: `data-project-id` is the
 * shell's own derivation rendered into the DOM, so "the sidebar showed the
 * workspace state" cannot pass against a shell that matched a project id and
 * simply failed to render its rail — and the positive control on a project
 * route proves the same render path does produce the project state.
 */
import {render, screen, within} from '@testing-library/react';
import {beforeEach, describe, expect, it, vi} from 'vitest';

vi.mock('@/contexts/AuthContext', () => ({
    AuthProvider: ({children}: {children: React.ReactNode}) => <>{children}</>,
    useAuth: () => ({user: {id: 'u1'}, session: null, loading: false, signOut: vi.fn()}),
}));

// Page bodies are not under test; the shell around them is. ExtractionFullScreen
// is mocked too so the run-route test has a positive control — without it, its
// `queryByTestId('app-shell')` negative would also pass against a route that
// rendered nothing at all.
vi.mock('@/pages/Dashboard', () => ({default: () => <div>hub page</div>}));
vi.mock('@/pages/ProjectView', () => ({default: () => <div>project view</div>}));
vi.mock('@/pages/UserSettings', () => ({default: () => <div>settings page</div>}));
vi.mock('@/pages/ExtractionFullScreen', () => ({default: () => <div>run workspace</div>}));
vi.mock('@/pages/OAuthConsent', () => ({default: () => <div>consent page</div>}));
vi.mock('@/pages/NotFound', () => ({default: () => <div>not found page</div>}));
// The footer pulls in the authed user menu and the feedback dialog.
vi.mock('@/components/layout/SidebarFooter', () => ({
    SidebarFooter: () => <div data-testid="sidebar-footer" />,
}));
// The Topbar's FIRST statement is `useUserProfile()`, which issues a real
// Supabase read against the stubbed URL; until it settles the bar renders a
// skeleton with no breadcrumb, no toggles and no view switcher. Unmocked, every
// Topbar assertion (Task 7 appends six) races a connection-refused round trip
// inside findBy*'s 1000 ms budget. NotificationCenter likewise starts
// background-job polling. Both are stubbed so the bar renders synchronously.
vi.mock('@/hooks/useNavigation', () => ({
    useUserProfile: () => ({
        user: {id: 'u1', name: 'Test User', email: 't@example.com', initials: 'T'},
        isLoading: false,
        error: null,
        refreshProfile: vi.fn(),
    }),
}));
vi.mock('@/components/navigation/NotificationCenter', () => ({
    NotificationCenter: () => <div data-testid="notification-center" />,
}));
vi.mock('@/hooks/useProjectsQuery', () => ({
    useProjectsQuery: () => ({
        data: [{id: 'p1', name: 'Alpha', description: null, created_at: '2026-01-01T00:00:00Z', is_active: true, review_title: null}],
        isLoading: false,
        isError: false,
        refetch: vi.fn(),
    }),
}));
vi.mock('@/hooks/useProjectMemberRole', () => ({
    useProjectMemberRole: () => ({role: 'reviewer', isManager: false, loading: false}),
}));

import App from '@/App';

function renderAt(path: string) {
    window.history.pushState({}, '', path);
    render(<App/>);
}

describe('AppShell', () => {
    beforeEach(() => {
        window.history.pushState({}, '', '/');
    });

    it('positive control — a project route yields a project id and the project rail', async () => {
        renderAt('/projects/p1?tab=articles');

        const shell = await screen.findByTestId('app-shell');
        expect(shell).toHaveAttribute('data-project-id', 'p1');
        expect(within(shell).getByRole('button', {name: 'Articles'})).toBeInTheDocument();
        expect(await screen.findByText('project view')).toBeInTheDocument();
    });

    it('renders the workspace shell on / — and the route match yielded no project id', async () => {
        renderAt('/');

        const shell = await screen.findByTestId('app-shell');
        expect(shell).toHaveAttribute('data-project-id', '');
        expect(within(shell).getByRole('button', {name: 'Projects'})).toBeInTheDocument();
        expect(within(shell).getByRole('button', {name: 'Settings'})).toBeInTheDocument();
        expect(within(shell).queryByRole('button', {name: 'Articles'})).toBeNull();
        expect(screen.getByTestId('sidebar-footer')).toBeInTheDocument();
        expect(await screen.findByText('hub page')).toBeInTheDocument();
    });

    // jsdom has no layout, so this pins the mechanism: without a positioned
    // root, an `sr-only` span deep in a scrolled pane takes the viewport as its
    // containing block, escapes `overflow-hidden`, and stretches the document,
    // so the window scrolls and drags the sidebar off screen.
    it('is the containing block for absolutely positioned descendants', async () => {
        renderAt('/settings');

        const shell = await screen.findByTestId('app-shell');
        expect(shell).toHaveClass('relative', 'overflow-hidden');
    });

    it('renders the workspace shell on /settings — and the route match yielded no project id', async () => {
        renderAt('/settings');

        const shell = await screen.findByTestId('app-shell');
        expect(shell).toHaveAttribute('data-project-id', '');
        expect(screen.getByTestId('sidebar-footer')).toBeInTheDocument();
        expect(await screen.findByText('settings page')).toBeInTheDocument();
    });

    it('does not wrap the full-screen run routes', async () => {
        renderAt('/projects/p1/extraction/a9');

        // POSITIVE CONTROL: the run page really did render. Do NOT assert
        // `sidebar-footer` here — RunWorkspaceShell mounts
        // `<SidebarProvider defaultCollapsed persist={false}>`
        // (`RunWorkspaceShell.tsx:72`), and ResizablePanel returns null while
        // collapsed (`resizable-panel.tsx:279`), so ProjectSidebar and its
        // footer are unmounted on this route by design. The mobile drawer is
        // closed, so its copy is unmounted too. `RunWorkspaceShell.test.tsx:63-65`
        // documents exactly this.
        expect(await screen.findByText('run workspace')).toBeInTheDocument();
        // RunWorkspaceShell, not AppShell: no Topbar, hence no app-shell root.
        expect(screen.queryByTestId('app-shell')).toBeNull();
    });

    it('renders the consent page outside the app shell', async () => {
        renderAt('/oauth/consent?request=11111111-1111-4111-8111-111111111111');

        expect(await screen.findByText('consent page')).toBeInTheDocument();
        expect(screen.queryByTestId('app-shell')).toBeNull();
    });

    it('matches the consent route only in lowercase', async () => {
        // The frame headers in vercel.json cover the exact lowercase path only.
        renderAt('/OAuth/consent?request=11111111-1111-4111-8111-111111111111');

        expect(await screen.findByText('not found page')).toBeInTheDocument();
        expect(screen.queryByText('consent page')).toBeNull();
    });

    it('names the page in a breadcrumb on every shell route', async () => {
        renderAt('/');
        const crumbs = await screen.findByRole('navigation', {name: 'Breadcrumb'});
        expect(within(crumbs).getByText('Projects')).toBeInTheDocument();
    });

    it('shows project › section on a project route', async () => {
        renderAt('/projects/p1?tab=extraction');
        const crumbs = await screen.findByRole('navigation', {name: 'Breadcrumb'});
        expect(within(crumbs).getByText('Alpha')).toBeInTheDocument();
        expect(within(crumbs).getByText('Data extraction')).toBeInTheDocument();
    });

    it('shows Settings on /settings', async () => {
        renderAt('/settings');
        const crumbs = await screen.findByRole('navigation', {name: 'Breadcrumb'});
        expect(within(crumbs).getByText('Settings')).toBeInTheDocument();
    });

    it('offers the sidebar toggle on every shell route, not just project routes', async () => {
        renderAt('/');
        expect(await screen.findByRole('button', {name: 'Toggle sidebar'})).toBeInTheDocument();
        expect(screen.getByRole('button', {name: 'Open menu'})).toBeInTheDocument();
    });

    it('drops the Topbar brand block — the sidebar header owns brand now', async () => {
        renderAt('/');
        const shell = await screen.findByTestId('app-shell');
        // NON-VACUITY GUARD: "exactly one Prumo" would also hold while the
        // Topbar is showing its loading skeleton (the single match then coming
        // from the sidebar brand header alone). Assert the breadcrumb in the
        // same render so the count is only meaningful once the real bar is up.
        expect(within(shell).getByRole('navigation', {name: 'Breadcrumb'})).toBeInTheDocument();
        // Exactly one "Prumo" in the shell: the sidebar brand header.
        expect(within(shell).getAllByText('Prumo')).toHaveLength(1);
    });

    it('keeps the QA view-switcher testid on a quality route', async () => {
        renderAt('/projects/p1?tab=quality');
        expect(await screen.findByTestId('hitl-quality_assessment-tab-assessment')).toBeInTheDocument();
    });
});
