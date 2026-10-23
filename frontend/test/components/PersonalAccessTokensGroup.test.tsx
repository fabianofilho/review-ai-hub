import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {render, screen, waitFor, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {TooltipProvider} from '@/components/ui/tooltip';
import {ApiError} from '@/integrations/api/client';
import {t} from '@/lib/copy';

vi.mock('@/services/personalAccessTokenService', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/services/personalAccessTokenService')>()),
  fetchMyTokens: vi.fn(),
  createMyToken: vi.fn(),
  revokeMyToken: vi.fn(),
}));
vi.mock('sonner', () => ({toast: {success: vi.fn(), error: vi.fn()}}));

const P1 = '11111111-1111-4111-8111-111111111111';
const P2 = '22222222-2222-4222-8222-222222222222';
const GONE = '99999999-9999-4999-8999-999999999999';
type ProjectsState = {isPending: boolean; isError: boolean; isSuccess: boolean; data: {id: string; name: string}[] | undefined};
const LOADED = (data: {id: string; name: string}[]): ProjectsState => ({isPending: false, isError: false, isSuccess: true, data});
const PROJECTS_LOADING: ProjectsState = {isPending: true, isError: false, isSuccess: false, data: undefined};
const PROJECTS_ERROR: ProjectsState = {isPending: false, isError: true, isSuccess: false, data: undefined};
const {projectsState, refetchProjects} = vi.hoisted(() => ({projectsState: {current: undefined as unknown}, refetchProjects: vi.fn()}));
vi.mock('@/hooks/useProjectsQuery', () => ({
  useProjectsQuery: () => ({refetch: refetchProjects, ...(projectsState.current as object)}),
}));

import {toast} from 'sonner';
import * as svc from '@/services/personalAccessTokenService';
import {PersonalAccessTokensGroup} from '@/components/user/PersonalAccessTokensGroup';

const ACTIVE = {
  id: 'active-1', name: 'Claude Code', token_prefix: 'prumo_pat_abc123', scope: 'read', status: 'active',
  expires_at: '2026-12-01T12:00:00Z', last_used_at: null, revoked_at: null, created_at: '2026-01-01T00:00:00Z',
} as never;
const EXPIRED = {
  id: 'expired-1', name: 'Old agent', token_prefix: 'prumo_pat_old999', scope: 'read', status: 'expired',
  expires_at: '2026-01-02T12:00:00Z', last_used_at: null, revoked_at: null, created_at: '2025-10-01T00:00:00Z',
} as never;
const REVOKED = {
  id: 'revoked-1', name: 'Retired agent', token_prefix: 'prumo_pat_rev777', scope: 'read_write', status: 'revoked',
  expires_at: '2026-06-01T12:00:00Z', last_used_at: null, revoked_at: '2026-02-03T12:00:00Z', created_at: '2025-11-01T00:00:00Z',
} as never;

beforeEach(() => {
  vi.clearAllMocks();
  projectsState.current = LOADED([{id: P1, name: 'Alpha review'}, {id: P2, name: 'Beta review'}]);
  vi.stubEnv('VITE_API_URL', 'https://api.test');
});
afterEach(() => vi.stubEnv('VITE_API_URL', ''));

function renderGroup() {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}});
  const tree = () => (
    <QueryClientProvider client={client}>
      <TooltipProvider><PersonalAccessTokensGroup /></TooltipProvider>
    </QueryClientProvider>
  );
  const view = render(tree());
  return {client, ...view, rerenderTree: () => view.rerender(tree())};
}

async function openCreateDialog() {
  await userEvent.click(screen.getByRole('button', {name: t('personalAccessTokens', 'createButton')}));
  return screen.getByRole('dialog');
}

describe('PersonalAccessTokensGroup', () => {
  it('loading: shows the skeleton list and disables the create button', async () => {
    vi.mocked(svc.fetchMyTokens).mockReturnValue(new Promise(() => {}));
    renderGroup();
    expect(screen.getByLabelText(t('personalAccessTokens', 'listLoading'))).toBeInTheDocument();
    expect(screen.getByRole('button', {name: t('personalAccessTokens', 'createButton')})).toBeDisabled();
  });

  it('empty: shows the empty line, the recommendation and clients note, with an enabled create button', async () => {
    vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: []});
    renderGroup();
    await waitFor(() => expect(screen.getByText(t('personalAccessTokens', 'listEmpty'))).toBeInTheDocument());
    expect(screen.getByRole('button', {name: t('personalAccessTokens', 'createButton')})).not.toBeDisabled();
    expect(screen.getByText(t('personalAccessTokens', 'readRecommendation'))).toBeInTheDocument();
    const note = screen.getByText(t('personalAccessTokens', 'clientsNote'));
    expect(note).toBeInTheDocument();
    expect(note.textContent).toMatch(/claude\.ai/);
    expect(note.textContent).not.toMatch(/not supported/i);
  });

  it('list error: shows the error and retry; retry refetches and the create button stays enabled', async () => {
    vi.mocked(svc.fetchMyTokens)
      .mockResolvedValueOnce({ok: false, error: new Error('x')})
      .mockResolvedValue({ok: true, data: [ACTIVE]});
    renderGroup();
    await waitFor(() => expect(screen.getByText(t('personalAccessTokens', 'listLoadError'))).toBeInTheDocument());
    expect(screen.getByRole('button', {name: t('personalAccessTokens', 'createButton')})).not.toBeDisabled();
    await userEvent.click(screen.getByRole('button', {name: t('personalAccessTokens', 'retry')}));
    await waitFor(() => expect(screen.getByText('Claude Code')).toBeInTheDocument());
  });

  it('rows: active shows its data and a revoke control; expired and revoked are muted with no revoke control', async () => {
    vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: [ACTIVE, EXPIRED, REVOKED]});
    renderGroup();
    await waitFor(() => expect(screen.getByText('Claude Code')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', {name: 'Show 2 inactive'}));

    const rows = screen.getAllByRole('listitem');
    expect(rows).toHaveLength(3);

    const activeRow = rows[0];
    expect(within(activeRow).getByText('prumo_pat_abc123…')).toBeInTheDocument();
    expect(within(activeRow).getByText(t('personalAccessTokens', 'neverUsed'))).toBeInTheDocument();
    expect(within(activeRow).getByRole('button', {name: t('personalAccessTokens', 'revokeAria')})).toBeInTheDocument();
    expect(activeRow).not.toHaveAttribute('data-muted', 'true');

    const expiredRow = rows[1];
    expect(expiredRow).toHaveAttribute('data-muted', 'true');
    expect(within(expiredRow).getByText('Expired 1/2/2026')).toBeInTheDocument();
    expect(within(expiredRow).queryByRole('button', {name: t('personalAccessTokens', 'revokeAria')})).not.toBeInTheDocument();

    // Narrow widths: the badges wrap under the name instead of squeezing it to "R…".
    expect(within(expiredRow).getByText('Old agent')).toHaveClass('min-w-[12ch]');

    const revokedRow = rows[2];
    expect(revokedRow).toHaveAttribute('data-muted', 'true');
    expect(within(revokedRow).getByText('Revoked 2/3/2026')).toBeInTheDocument();
    expect(within(revokedRow).queryByRole('button', {name: t('personalAccessTokens', 'revokeAria')})).not.toBeInTheDocument();
  });

  it('rows share one column grid: every status fills the same date, last-used and action cells', async () => {
    vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: [ACTIVE, EXPIRED, REVOKED]});
    renderGroup();
    await screen.findByText('Claude Code');
    await userEvent.click(screen.getByRole('button', {name: 'Show 2 inactive'}));

    const rows = screen.getAllByRole('listitem');
    const template = (row: HTMLElement) => [...row.classList].find((c) => c.includes('grid-cols-['));
    expect(template(rows[0])).toBeDefined();
    for (const row of rows) {
      expect(template(row)).toBe(template(rows[0]));
      expect(row.querySelectorAll(':scope > [data-col]')).toHaveLength(5);
    }
    const dateCell = (row: HTMLElement) => row.querySelector(':scope > [data-col="date"]');
    expect(dateCell(rows[0])).toHaveTextContent('Expires 12/1/2026');
    expect(dateCell(rows[1])).toHaveTextContent('Expired 1/2/2026');
    expect(dateCell(rows[2])).toHaveTextContent('Revoked 2/3/2026');
    expect(rows[2].querySelector(':scope > [data-col="last-used"]')).toHaveTextContent(t('personalAccessTokens', 'neverUsed'));
  });

  it('inactive tokens collapse under a toggle that shows and hides them', async () => {
    vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: [ACTIVE, EXPIRED, REVOKED]});
    renderGroup();
    await screen.findByText('Claude Code');

    expect(screen.queryByText('Old agent')).not.toBeInTheDocument();
    expect(screen.queryByText('Retired agent')).not.toBeInTheDocument();
    const toggle = screen.getByRole('button', {name: 'Show 2 inactive'});
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await userEvent.click(toggle);
    expect(screen.getByText('Old agent')).toBeInTheDocument();
    expect(screen.getByText('Retired agent')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', {name: t('personalAccessTokens', 'inactiveHide')}));
    expect(screen.queryByText('Old agent')).not.toBeInTheDocument();
  });

  it('only inactive tokens: says there are no active tokens and offers the toggle', async () => {
    vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: [REVOKED]});
    renderGroup();
    expect(await screen.findByText(t('personalAccessTokens', 'listNoActive'))).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Show 1 inactive'})).toBeInTheDocument();
    expect(screen.queryByText(t('personalAccessTokens', 'listEmpty'))).not.toBeInTheDocument();
  });

  it('no inactive tokens: no toggle', async () => {
    vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: [ACTIVE]});
    renderGroup();
    await screen.findByText('Claude Code');
    expect(screen.queryByRole('button', {name: /inactive/})).not.toBeInTheDocument();
  });

  it('create at the token cap: shows the limit copy inline and keeps the dialog open', async () => {
    vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: []});
    vi.mocked(svc.createMyToken).mockResolvedValue({ok: false, error: new ApiError('TOKEN_LIMIT_REACHED', 'limit', 409)});
    renderGroup();
    await waitFor(() => expect(screen.getByText(t('personalAccessTokens', 'listEmpty'))).toBeInTheDocument());

    const dialog = await openCreateDialog();
    await userEvent.type(within(dialog).getByLabelText(t('personalAccessTokens', 'nameLabel')), 'cli');
    await userEvent.click(within(dialog).getByRole('button', {name: t('personalAccessTokens', 'createSubmit')}));

    await waitFor(() => expect(within(dialog).getByText(t('personalAccessTokens', 'createLimitError'))).toBeInTheDocument());
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('create validation error: shows the server detail inline and keeps the dialog open', async () => {
    vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: []});
    vi.mocked(svc.createMyToken).mockResolvedValue({ok: false, error: new ApiError('VALIDATION_ERROR', 'name: too long', 422)});
    renderGroup();
    await waitFor(() => expect(screen.getByText(t('personalAccessTokens', 'listEmpty'))).toBeInTheDocument());

    const dialog = await openCreateDialog();
    await userEvent.type(within(dialog).getByLabelText(t('personalAccessTokens', 'nameLabel')), 'cli');
    await userEvent.click(within(dialog).getByRole('button', {name: t('personalAccessTokens', 'createSubmit')}));

    await waitFor(() => expect(within(dialog).getByText('name: too long')).toBeInTheDocument());
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  describe('AI runs grant', () => {
    const aiBoxName = t('personalAccessTokens', 'aiRunLabel');
    const expiryName = t('personalAccessTokens', 'expiryLabel');
    const days = (n: number) => t('personalAccessTokens', 'expiryDays').replace('{{n}}', String(n));

    it('the AI runs box is unchecked by default, explains itself, and the POST carries ai_run: false', async () => {
      vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: []});
      vi.mocked(svc.createMyToken).mockResolvedValue({ok: true, data: {secret: 's', token: ACTIVE}});
      renderGroup();
      await screen.findByText(t('personalAccessTokens', 'listEmpty'));

      const dialog = await openCreateDialog();
      const box = within(dialog).getByRole('checkbox', {name: aiBoxName});
      expect(box).not.toBeChecked();
      expect(box).toHaveAccessibleDescription(t('personalAccessTokens', 'aiRunHint'));
      await userEvent.type(within(dialog).getByLabelText(t('personalAccessTokens', 'nameLabel')), 'cli');
      await userEvent.click(within(dialog).getByRole('button', {name: t('personalAccessTokens', 'createSubmit')}));

      await waitFor(() => expect(svc.createMyToken).toHaveBeenCalled());
      expect(vi.mocked(svc.createMyToken).mock.calls[0][0]).toMatchObject({ai_run: false, expires_in_days: 90});
    });

    it('checking it resets a longer expiry to 30 days, offers only 30, and the POST carries ai_run: true', async () => {
      vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: []});
      vi.mocked(svc.createMyToken).mockResolvedValue({ok: true, data: {secret: 's', token: ACTIVE}});
      renderGroup();
      await screen.findByText(t('personalAccessTokens', 'listEmpty'));

      const dialog = await openCreateDialog();
      await userEvent.type(within(dialog).getByLabelText(t('personalAccessTokens', 'nameLabel')), 'agent');
      await userEvent.click(within(dialog).getByRole('combobox', {name: expiryName}));
      await userEvent.click(screen.getByRole('option', {name: days(365)}));
      expect(within(dialog).getByRole('combobox', {name: expiryName})).toHaveTextContent(days(365));

      await userEvent.click(within(dialog).getByRole('checkbox', {name: aiBoxName}));
      expect(within(dialog).getByRole('combobox', {name: expiryName})).toHaveTextContent(days(30));
      await userEvent.click(within(dialog).getByRole('combobox', {name: expiryName}));
      expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual([days(30)]);
      await userEvent.keyboard('{Escape}');

      await userEvent.click(within(dialog).getByRole('button', {name: t('personalAccessTokens', 'createSubmit')}));
      await waitFor(() => expect(svc.createMyToken).toHaveBeenCalled());
      expect(vi.mocked(svc.createMyToken).mock.calls[0][0]).toEqual({name: 'agent', scope: 'read', expires_in_days: 30, ai_run: true});
    });

    it('a row carrying ai_run shows the AI runs badge; one without it does not', async () => {
      const AI_ROW = {...(ACTIVE as object), id: 'ai-1', name: 'Agent token', ai_run: true} as never;
      const PLAIN_ROW = {...(ACTIVE as object), id: 'plain-1', name: 'Plain token', ai_run: false} as never;
      vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: [AI_ROW, PLAIN_ROW]});
      renderGroup();
      await screen.findByText('Agent token');

      const [aiRow, plainRow] = screen.getAllByRole('listitem');
      expect(within(aiRow).getByText(t('personalAccessTokens', 'aiRunsBadge'))).toBeInTheDocument();
      expect(within(plainRow).queryByText(t('personalAccessTokens', 'aiRunsBadge'))).not.toBeInTheDocument();
    });

    it('a refused create with the box checked still shows the error inline and keeps the dialog open', async () => {
      vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: []});
      vi.mocked(svc.createMyToken).mockResolvedValue({ok: false, error: new ApiError('VALIDATION_ERROR', 'expiry too long', 422)});
      renderGroup();
      await screen.findByText(t('personalAccessTokens', 'listEmpty'));

      const dialog = await openCreateDialog();
      await userEvent.type(within(dialog).getByLabelText(t('personalAccessTokens', 'nameLabel')), 'agent');
      await userEvent.click(within(dialog).getByRole('checkbox', {name: aiBoxName}));
      await userEvent.click(within(dialog).getByRole('button', {name: t('personalAccessTokens', 'createSubmit')}));

      expect(await within(dialog).findByText('expiry too long')).toBeInTheDocument();
      expect(within(dialog).getByRole('checkbox', {name: aiBoxName})).toBeChecked();
    });
  });

  it('reveal: shows the secret once, survives Escape, and clears from state and the mutation cache on done', async () => {
    vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: []});
    vi.mocked(svc.createMyToken).mockResolvedValue({ok: true, data: {secret: 'prumo_pat_SECRET', token: ACTIVE}});
    const {client} = renderGroup();
    await waitFor(() => expect(screen.getByText(t('personalAccessTokens', 'listEmpty'))).toBeInTheDocument());

    const dialog = await openCreateDialog();
    await userEvent.type(within(dialog).getByLabelText(t('personalAccessTokens', 'nameLabel')), 'cli');
    await userEvent.click(within(dialog).getByRole('button', {name: t('personalAccessTokens', 'createSubmit')}));

    await waitFor(() => expect(screen.getByText(t('personalAccessTokens', 'revealTitle'))).toBeInTheDocument());
    expect(screen.getByText('prumo_pat_SECRET')).toBeInTheDocument();
    expect(screen.getByText(t('personalAccessTokens', 'revealWarning'))).toBeInTheDocument();
    expect(screen.getByText(t('personalAccessTokens', 'tokenLabel'))).toBeInTheDocument();
    expect(screen.getByRole('button', {name: t('personalAccessTokens', 'copyTokenAria')})).toBeInTheDocument();

    for (const key of ['chipClaudeCode', 'chipCursor', 'chipVsCode', 'chipGeminiCli', 'chipCodex', 'chipWindsurf'] as const) {
      expect(screen.getByRole('radio', {name: t('personalAccessTokens', key)})).toBeInTheDocument();
    }
    expect(screen.queryByRole('radio', {name: t('personalAccessTokens', 'chipClaudeAi')})).not.toBeInTheDocument();
    expect(screen.getByText('claude mcp add --transport http prumo https://api.test/mcp --header "Authorization: Bearer prumo_pat_SECRET"')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('radio', {name: t('personalAccessTokens', 'chipCursor')}));
    const cursorPre = screen.getAllByText((_, el) => el?.tagName === 'PRE' && (el.textContent ?? '').startsWith('{'))[0];
    expect(JSON.parse(cursorPre.textContent ?? '')).toEqual({
      mcpServers: {prumo: {url: 'https://api.test/mcp', headers: {Authorization: 'Bearer prumo_pat_SECRET'}}},
    });

    await userEvent.keyboard('{Escape}');
    expect(screen.getByText('prumo_pat_SECRET')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', {name: t('personalAccessTokens', 'revealDone')}));
    expect(screen.queryByText('prumo_pat_SECRET')).toBeNull();
    await waitFor(() =>
      expect(
        JSON.stringify(client.getMutationCache().getAll().map((m) => m.state.data)),
      ).not.toContain('prumo_pat_SECRET'),
    );
  });

  it('revoke: confirms, disables while pending, then toasts success', async () => {
    vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: [ACTIVE]});
    let resolveRevoke: (v: {ok: true; data: undefined}) => void = () => {};
    vi.mocked(svc.revokeMyToken).mockReturnValue(new Promise((resolve) => { resolveRevoke = resolve; }));
    renderGroup();
    await waitFor(() => expect(screen.getByText('Claude Code')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', {name: t('personalAccessTokens', 'revokeAria')}));
    const alert = screen.getByRole('alertdialog');
    expect(within(alert).getByText(/Claude Code/)).toBeInTheDocument();

    await userEvent.click(within(alert).getByRole('button', {name: t('personalAccessTokens', 'revokeConfirm')}));
    const confirmButton = within(alert).getByRole('button', {name: t('personalAccessTokens', 'revoking')});
    expect(confirmButton).toBeDisabled();

    resolveRevoke({ok: true, data: undefined});
    await waitFor(() => expect(svc.revokeMyToken).toHaveBeenCalledWith('active-1'));
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith(t('personalAccessTokens', 'revokeSuccess')));
  });

  it('revoke: Cancel closes the confirmation dialog without revoking', async () => {
    vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: [ACTIVE]});
    renderGroup();
    await waitFor(() => expect(screen.getByText('Claude Code')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', {name: t('personalAccessTokens', 'revokeAria')}));
    const alert = screen.getByRole('alertdialog');

    await userEvent.click(within(alert).getByRole('button', {name: t('personalAccessTokens', 'cancel')}));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(svc.revokeMyToken).not.toHaveBeenCalled();
    expect(screen.getByText('Claude Code')).toBeInTheDocument();
  });

  it('revoke error: toasts the server message and keeps the row', async () => {
    vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: [ACTIVE]});
    vi.mocked(svc.revokeMyToken).mockResolvedValue({ok: false, error: new Error('gone')});
    renderGroup();
    await waitFor(() => expect(screen.getByText('Claude Code')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', {name: t('personalAccessTokens', 'revokeAria')}));
    const alert = screen.getByRole('alertdialog');
    await userEvent.click(within(alert).getByRole('button', {name: t('personalAccessTokens', 'revokeConfirm')}));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('gone'));
    expect(screen.getByText('Claude Code')).toBeInTheDocument();
  });

  it('reveal closed over a populated list: only the prefix stays on screen', async () => {
    const created = {...(ACTIVE as object), id: 'new-1', name: 'cli', token_prefix: 'prumo_pat_new456'} as never;
    vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: [ACTIVE]});
    vi.mocked(svc.createMyToken).mockResolvedValue({ok: true, data: {secret: 'prumo_pat_new456SECRETTAIL', token: created}});
    renderGroup();
    await waitFor(() => expect(screen.getByText('Claude Code')).toBeInTheDocument());

    const dialog = await openCreateDialog();
    await userEvent.type(within(dialog).getByLabelText(t('personalAccessTokens', 'nameLabel')), 'cli');
    vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: [created, ACTIVE]});
    await userEvent.click(within(dialog).getByRole('button', {name: t('personalAccessTokens', 'createSubmit')}));
    await waitFor(() => expect(screen.getByText('prumo_pat_new456SECRETTAIL')).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', {name: t('personalAccessTokens', 'revealDone')}));
    await waitFor(() => expect(screen.getByText('prumo_pat_new456…')).toBeInTheDocument());
    expect(document.body.textContent).not.toContain('SECRETTAIL');
  });

  describe('project restriction', () => {
    async function openWithName() {
      vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: []});
      const view = renderGroup();
      await waitFor(() => expect(screen.getByText(t('personalAccessTokens', 'listEmpty'))).toBeInTheDocument());
      const dialog = await openCreateDialog();
      await userEvent.type(within(dialog).getByLabelText(t('personalAccessTokens', 'nameLabel')), 'cli');
      return Object.assign(dialog, {view});
    }
    const submitButton = (dialog: HTMLElement) =>
      within(dialog).getByRole('button', {name: t('personalAccessTokens', 'createSubmit')});
    const countLine = (n: number) =>
      t('personalAccessTokens', 'projectsSelectedCount').replace('{{n}}', String(n));

    it('default: "All my projects" is selected and the request carries no project_ids', async () => {
      vi.mocked(svc.createMyToken).mockResolvedValue({ok: true, data: {secret: 's', token: ACTIVE}});
      const dialog = await openWithName();
      expect(within(dialog).getByRole('radio', {name: t('personalAccessTokens', 'projectsAll')})).toBeChecked();

      await userEvent.click(submitButton(dialog));

      await waitFor(() => expect(svc.createMyToken).toHaveBeenCalled());
      expect(vi.mocked(svc.createMyToken).mock.calls[0][0]).toEqual({name: 'cli', scope: 'read', expires_in_days: 90, ai_run: false});
    });

    it('"Only these projects": lists the user\'s projects and posts the selected ids', async () => {
      vi.mocked(svc.createMyToken).mockResolvedValue({ok: true, data: {secret: 's', token: ACTIVE}});
      const dialog = await openWithName();
      await userEvent.click(within(dialog).getByRole('radio', {name: t('personalAccessTokens', 'projectsOnly')}));
      await userEvent.click(within(dialog).getByRole('checkbox', {name: 'Beta review'}));
      expect(within(dialog).getByRole('checkbox', {name: 'Alpha review'})).not.toBeChecked();

      await userEvent.click(submitButton(dialog));

      await waitFor(() => expect(svc.createMyToken).toHaveBeenCalled());
      expect(vi.mocked(svc.createMyToken).mock.calls[0][0]).toEqual({
        name: 'cli', scope: 'read', expires_in_days: 90, ai_run: false, project_ids: [P2],
      });
    });

    it('loading: the "Only these projects" option is disabled with a spinner', async () => {
      projectsState.current = PROJECTS_LOADING;
      const dialog = await openWithName();
      expect(within(dialog).getByRole('radio', {name: t('personalAccessTokens', 'projectsOnly')})).toBeDisabled();
      expect(within(dialog).getByRole('status', {name: t('personalAccessTokens', 'projectsLoading')})).toBeInTheDocument();
      expect(submitButton(dialog)).not.toBeDisabled();
    });

    it('empty: says the user is in no project and disables the option', async () => {
      projectsState.current = LOADED([]);
      const dialog = await openWithName();
      expect(within(dialog).getByText(t('personalAccessTokens', 'projectsEmpty'))).toBeInTheDocument();
      expect(within(dialog).getByRole('radio', {name: t('personalAccessTokens', 'projectsOnly')})).toBeDisabled();
    });

    it('error: shows an inline error and "All my projects" still creates', async () => {
      projectsState.current = PROJECTS_ERROR;
      vi.mocked(svc.createMyToken).mockResolvedValue({ok: true, data: {secret: 's', token: ACTIVE}});
      const dialog = await openWithName();
      expect(within(dialog).getByText(t('personalAccessTokens', 'projectsLoadError'))).toBeInTheDocument();
      expect(within(dialog).getByRole('radio', {name: t('personalAccessTokens', 'projectsOnly')})).toBeDisabled();

      await userEvent.click(submitButton(dialog));
      await waitFor(() => expect(svc.createMyToken).toHaveBeenCalled());
    });

    it('more than 20 selected: submit is disabled with a hint', async () => {
      const many = Array.from({length: 21}, (_, i) => ({
        id: `00000000-0000-4000-8000-${String(i).padStart(12, '0')}`, name: `Project ${i}`,
      }));
      projectsState.current = LOADED(many);
      const dialog = await openWithName();
      await userEvent.click(within(dialog).getByRole('radio', {name: t('personalAccessTokens', 'projectsOnly')}));
      for (const p of many.slice(0, 20)) await userEvent.click(within(dialog).getByRole('checkbox', {name: p.name}));
      expect(submitButton(dialog)).not.toBeDisabled();
      expect(within(dialog).queryByText(t('personalAccessTokens', 'projectsTooMany'))).not.toBeInTheDocument();

      await userEvent.click(within(dialog).getByRole('checkbox', {name: 'Project 20'}));

      expect(submitButton(dialog)).toBeDisabled();
      expect(within(dialog).getByText(countLine(21))).toBeInTheDocument();
      expect(await within(dialog).findByText(t('personalAccessTokens', 'projectsTooMany'))).toBeInTheDocument();
    }, 15_000);

    it('422 PROJECT_NOT_ACCESSIBLE: shows the inline refusal and keeps the dialog open', async () => {
      vi.mocked(svc.createMyToken).mockResolvedValue({
        ok: false, error: new ApiError('PROJECT_NOT_ACCESSIBLE', 'project not accessible', 422),
      });
      const dialog = await openWithName();
      await userEvent.click(within(dialog).getByRole('radio', {name: t('personalAccessTokens', 'projectsOnly')}));
      await userEvent.click(within(dialog).getByRole('checkbox', {name: 'Alpha review'}));
      await userEvent.click(submitButton(dialog));

      await waitFor(() => expect(within(dialog).getByText(t('personalAccessTokens', 'projectNotAccessible'))).toBeInTheDocument());
      expect(screen.getByRole('dialog')).toBeInTheDocument();
      expect(refetchProjects).toHaveBeenCalled();
    });

    it('after the refusal, a project gone from the refreshed list is dropped from the selection', async () => {
      vi.mocked(svc.createMyToken)
        .mockResolvedValueOnce({ok: false, error: new ApiError('PROJECT_NOT_ACCESSIBLE', 'gone', 422)})
        .mockResolvedValue({ok: true, data: {secret: 's', token: ACTIVE}});
      const dialog = await openWithName();
      await userEvent.click(within(dialog).getByRole('radio', {name: t('personalAccessTokens', 'projectsOnly')}));
      await userEvent.click(within(dialog).getByRole('checkbox', {name: 'Alpha review'}));
      await userEvent.click(within(dialog).getByRole('checkbox', {name: 'Beta review'}));
      await userEvent.click(submitButton(dialog));
      await waitFor(() => expect(within(dialog).getByText(t('personalAccessTokens', 'projectNotAccessible'))).toBeInTheDocument());

      projectsState.current = LOADED([{id: P2, name: 'Beta review'}]);
      dialog.view.rerenderTree();

      await waitFor(() => expect(within(dialog).getByText(countLine(1))).toBeInTheDocument());
      await userEvent.click(submitButton(dialog));
      await waitFor(() => expect(svc.createMyToken).toHaveBeenCalledTimes(2));
      expect(vi.mocked(svc.createMyToken).mock.calls[1][0]).toEqual({
        name: 'cli', scope: 'read', expires_in_days: 90, ai_run: false, project_ids: [P2],
      });
    });

    it('"Only these projects" with none selected: the count line explains the disabled Create', async () => {
      const dialog = await openWithName();
      await userEvent.click(within(dialog).getByRole('radio', {name: t('personalAccessTokens', 'projectsOnly')}));
      const count = within(dialog).getByText(countLine(0));
      expect(submitButton(dialog)).toBeDisabled();
      expect(submitButton(dialog)).toHaveAttribute('aria-describedby', count.id);
      expect(within(dialog).getByRole('group', {name: t('personalAccessTokens', 'projectsOnly')})).toBeInTheDocument();

      await userEvent.click(within(dialog).getByRole('checkbox', {name: 'Alpha review'}));
      expect(within(dialog).getByText(countLine(1))).toBeInTheDocument();
      expect(submitButton(dialog)).not.toBeDisabled();
      expect(submitButton(dialog)).not.toHaveAttribute('aria-describedby');
    });

    it('projects error: Retry refetches the project list', async () => {
      projectsState.current = PROJECTS_ERROR;
      const dialog = await openWithName();
      await userEvent.click(within(dialog).getByRole('button', {name: t('personalAccessTokens', 'retry')}));
      expect(refetchProjects).toHaveBeenCalled();
    });

    const rowWith = (project_ids: string[] | null) => ({...(ACTIVE as object), project_ids}) as never;

    it('row: null project_ids shows "All projects"', async () => {
      vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: [rowWith(null)]});
      renderGroup();
      await waitFor(() => expect(screen.getByText(t('personalAccessTokens', 'projectsAllBadge'))).toBeInTheDocument());
    });

    it('row: two ids show "2 projects" and the names in a tooltip', async () => {
      vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: [rowWith([P1, P2])]});
      renderGroup();
      const badge = await screen.findByText('2 projects');
      await userEvent.hover(badge);
      const tip = await screen.findByRole('tooltip');
      expect(tip).toHaveTextContent('Alpha review');
      expect(tip).toHaveTextContent('Beta review');
    });

    it('row: an id with no known name shows "Unavailable project" in the tooltip', async () => {
      vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: [rowWith([P1, GONE])]});
      renderGroup();
      await userEvent.hover(await screen.findByText('2 projects'));
      const tip = await screen.findByRole('tooltip');
      expect(tip).toHaveTextContent('Alpha review');
      expect(tip).toHaveTextContent(t('personalAccessTokens', 'projectUnavailable'));
    });

    it.each([
      ['loading', PROJECTS_LOADING],
      ['errored', PROJECTS_ERROR],
    ])('row with projects %s: "2 projects" with no tooltip and no "Unavailable project"', async (_label, state) => {
      projectsState.current = state;
      vi.mocked(svc.fetchMyTokens).mockResolvedValue({ok: true, data: [rowWith([P1, GONE])]});
      renderGroup();
      const badge = await screen.findByText('2 projects');
      // No tooltip trigger is rendered at all until the list has loaded.
      expect(badge.closest('button')).toBeNull();
      expect(document.body.textContent).not.toContain(t('personalAccessTokens', 'projectUnavailable'));
    });
  });
});
