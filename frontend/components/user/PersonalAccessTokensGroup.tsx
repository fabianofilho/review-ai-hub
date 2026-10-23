/**
 * Settings → Integrations → Personal access tokens (spec §4.5, §4.7): list,
 * create, revoke, and the one-time secret reveal. Renders one SettingsGroup
 * as its root (borderless density pass § 4.3). The reveal dialog reuses
 * `McpClientSnippetSelector` (Task 4b) with the real secret.
 */
import {useEffect, useState, type MouseEvent} from 'react';
import {ChevronRight, Loader2, Plus, Trash2} from 'lucide-react';
import {toast} from 'sonner';
import {useForm, useWatch, type Control} from 'react-hook-form';
import {zodResolver} from '@hookform/resolvers/zod';
import {z} from 'zod';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import {IconButton} from '@/components/patterns/IconButton';
import {Badge} from '@/components/ui/badge';
import {Button} from '@/components/ui/button';
import {Checkbox} from '@/components/ui/checkbox';
import {Collapsible, CollapsibleContent, CollapsibleTrigger} from '@/components/ui/collapsible';
import {Form, FormControl, FormField, FormItem, FormMessage} from '@/components/ui/form';
import {RadioGroup, RadioGroupItem} from '@/components/ui/radio-group';
import {Tooltip, TooltipContent, TooltipTrigger} from '@/components/ui/tooltip';
import {Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle} from '@/components/ui/dialog';
import {Input} from '@/components/ui/input';
import {Select, SelectContent, SelectItem, SelectTrigger, SelectValue} from '@/components/ui/select';
import {Skeleton} from '@/components/ui/skeleton';
import {SettingsGroup, SettingsRow} from '@/components/settings';
import {CopyBlock} from '@/components/user/CopyBlock';
import {McpClientSnippetSelector} from '@/components/user/McpClientSnippetSelector';
import {TOKEN_CLIENT_IDS} from '@/lib/mcp/clientSnippets';
import {
  useCreateMyToken,
  useMyTokens,
  useRevokeMyToken,
} from '@/hooks/user/usePersonalAccessTokens';
import {useProjectsQuery} from '@/hooks/useProjectsQuery';
import {
  isProjectNotAccessibleError,
  isTokenLimitError,
  type PersonalAccessTokenRead,
} from '@/services/personalAccessTokenService';
import {relativeTime} from '@/lib/relative-time';
import {t} from '@/lib/copy';
import {cn} from '@/lib/utils';

const EXPIRY_OPTIONS = [30, 90, 365] as const;
/** A token that may start AI runs lives at most 30 days (the backend refuses longer). */
const AI_RUN_EXPIRY_OPTIONS = [30] as const;
const SCOPE_COPY = {read: 'scopeRead', read_write: 'scopeReadWrite'} as const;

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US');
}

type ProjectsQuery = ReturnType<typeof useProjectsQuery>;

/** "All projects" or "N projects"; the names show in a tooltip once the project list has loaded. */
function ProjectsBadge({ids, projects}: {ids: string[] | null | undefined; projects: ProjectsQuery}) {
  if (ids == null) {
    return <Badge variant="outline" className="shrink-0">{t('personalAccessTokens', 'projectsAllBadge')}</Badge>;
  }
  const label = ids.length === 1
    ? t('personalAccessTokens', 'projectsCountOne')
    : t('personalAccessTokens', 'projectsCount').replace('{{n}}', String(ids.length));
  if (!projects.isSuccess) {
    return <Badge variant="outline" className="shrink-0">{label}</Badge>;
  }
  const names = new Map(projects.data.map((project) => [project.id, project.name]));
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="shrink-0 rounded-full focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <Badge variant="outline">{label}</Badge>
        </button>
      </TooltipTrigger>
      <TooltipContent>
        <ul>
          {ids.map((id) => (
            <li key={id}>{names.get(id) ?? t('personalAccessTokens', 'projectUnavailable')}</li>
          ))}
        </ul>
      </TooltipContent>
    </Tooltip>
  );
}

/** The date cell: when an active token expires, or when an inactive one stopped working. */
function dateLabel(row: PersonalAccessTokenRead): string {
  if (row.status === 'revoked' && row.revoked_at) {
    return t('personalAccessTokens', 'revokedBadge').replace('{{date}}', formatDate(row.revoked_at));
  }
  if (row.status === 'expired') {
    return t('personalAccessTokens', 'expiredBadge').replace('{{date}}', formatDate(row.expires_at));
  }
  return t('personalAccessTokens', 'expiresOn').replace('{{date}}', formatDate(row.expires_at));
}

/** Every row fills the same five cells, so the columns line up whatever the status. */
function TokenRow({row, projects}: {row: PersonalAccessTokenRead; projects: ProjectsQuery}) {
  const [open, setOpen] = useState(false);
  const revoke = useRevokeMyToken();
  const onConfirm = (e: MouseEvent<HTMLButtonElement>) => {
    e.preventDefault();
    revoke.mutate(row.id, {
      onSuccess: () => {
        toast.success(t('personalAccessTokens', 'revokeSuccess'));
        setOpen(false);
      },
      onError: (error) => {
        toast.error(error.message || t('personalAccessTokens', 'revokeError'));
        setOpen(false);
      },
    });
  };
  return (
    <li
      data-muted={row.status !== 'active'}
      className={cn(
        'flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md px-2 py-1.5 text-[13px]',
        '@[36rem]/settings:grid @[36rem]/settings:grid-cols-[minmax(0,8rem)_minmax(0,1fr)_7.5rem_8.5rem_1.75rem] @[36rem]/settings:py-1',
        row.status !== 'active' && 'text-muted-foreground',
      )}
    >
      <span data-col="name" className="min-w-[12ch] max-w-full truncate font-medium @[36rem]/settings:min-w-0" title={row.name}>
        {row.name}
      </span>
      <div data-col="details" className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <code className="shrink-0 text-[12px] text-muted-foreground">{row.token_prefix}…</code>
        <Badge variant="secondary" className="shrink-0">{t('personalAccessTokens', SCOPE_COPY[row.scope])}</Badge>
        {row.ai_run && (
          <Badge variant="secondary" className="shrink-0">{t('personalAccessTokens', 'aiRunsBadge')}</Badge>
        )}
        <ProjectsBadge ids={row.project_ids} projects={projects} />
      </div>
      <span data-col="date" className="whitespace-nowrap text-muted-foreground">{dateLabel(row)}</span>
      <span data-col="last-used" className="whitespace-nowrap text-muted-foreground">
        {row.last_used_at
          ? t('personalAccessTokens', 'lastUsed').replace('{{when}}', relativeTime(row.last_used_at))
          : t('personalAccessTokens', 'neverUsed')}
      </span>
      <div data-col="action" className="ml-auto flex items-center justify-end">
        {row.status === 'active' && (
          <AlertDialog open={open} onOpenChange={setOpen}>
            <AlertDialogTrigger asChild>
              <IconButton label={t('personalAccessTokens', 'revokeAria')} icon={<Trash2 strokeWidth={1.5} />} />
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>{t('personalAccessTokens', 'revokeTitle')}</AlertDialogTitle>
                <AlertDialogDescription>
                  {t('personalAccessTokens', 'revokeDescription').replace('{{name}}', row.name)}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>{t('personalAccessTokens', 'cancel')}</AlertDialogCancel>
                <AlertDialogAction onClick={onConfirm} disabled={revoke.isPending}>
                  {revoke.isPending ? t('personalAccessTokens', 'revoking') : t('personalAccessTokens', 'revokeConfirm')}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>
    </li>
  );
}

/** Revoked and expired tokens stay listed for the audit trail, collapsed out of the way. */
function TokenList({rows, projects}: {rows: PersonalAccessTokenRead[]; projects: ProjectsQuery}) {
  const [showInactive, setShowInactive] = useState(false);
  const active = rows.filter((row) => row.status === 'active');
  const inactive = rows.filter((row) => row.status !== 'active');
  return (
    <>
      {active.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">{t('personalAccessTokens', 'listNoActive')}</p>
      ) : (
        <ul role="list">
          {active.map((row) => <TokenRow key={row.id} row={row} projects={projects} />)}
        </ul>
      )}
      {inactive.length > 0 && (
        <Collapsible open={showInactive} onOpenChange={setShowInactive}>
          <CollapsibleTrigger asChild>
            <Button size="sm" variant="ghost" className="text-muted-foreground">
              <ChevronRight
                className={cn('mr-1 h-4 w-4 transition-transform duration-75', showInactive && 'rotate-90')}
                strokeWidth={1.5}
              />
              {showInactive
                ? t('personalAccessTokens', 'inactiveHide')
                : t('personalAccessTokens', 'inactiveShow').replace('{{n}}', String(inactive.length))}
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ul role="list">
              {inactive.map((row) => <TokenRow key={row.id} row={row} projects={projects} />)}
            </ul>
          </CollapsibleContent>
        </Collapsible>
      )}
    </>
  );
}

const MAX_PROJECTS = 20;

const createSchema = z.object({
  name: z.string().trim(),
  scope: z.enum(['read', 'read_write']),
  expires_in_days: z.union([z.literal(30), z.literal(90), z.literal(365)]),
  ai_run: z.boolean(),
  projectMode: z.enum(['all', 'only']),
  project_ids: z.array(z.string().uuid()).max(MAX_PROJECTS, t('personalAccessTokens', 'projectsTooMany')).optional(),
});
type CreateValues = z.infer<typeof createSchema>;
const CREATE_DEFAULTS: CreateValues = {
  name: '', scope: 'read', expires_in_days: 90, ai_run: false, projectMode: 'all', project_ids: [],
};

function createErrorMessage(error: Error): string {
  if (isTokenLimitError(error)) return t('personalAccessTokens', 'createLimitError');
  if (isProjectNotAccessibleError(error)) return t('personalAccessTokens', 'projectNotAccessible');
  return error.message || t('personalAccessTokens', 'createError');
}

const PROJECTS_COUNT_ID = 'pat-projects-count';

/** All my projects, or a checkbox list of the caller's projects (at most 20). */
function ProjectsField({control, projects}: {control: Control<CreateValues>; projects: ProjectsQuery}) {
  const mode = useWatch({control, name: 'projectMode'});
  const loaded = projects.isSuccess ? projects.data : undefined;
  const canRestrict = loaded !== undefined && loaded.length > 0;
  return (
    <SettingsRow label={t('personalAccessTokens', 'projectsLabel')} align="start">
      <FormField
        control={control}
        name="projectMode"
        render={({field}) => (
          <RadioGroup
            aria-label={t('personalAccessTokens', 'projectsLabel')}
            value={field.value}
            onValueChange={field.onChange}
            className="gap-1.5 py-1"
          >
            <div className="flex items-center gap-2">
              <RadioGroupItem id="pat-projects-all" value="all" />
              <label htmlFor="pat-projects-all" className="text-[13px]">{t('personalAccessTokens', 'projectsAll')}</label>
            </div>
            <div className="flex items-center gap-2">
              <RadioGroupItem id="pat-projects-only" value="only" disabled={!canRestrict} />
              <label htmlFor="pat-projects-only" className={cn('text-[13px]', !canRestrict && 'text-muted-foreground')}>
                {t('personalAccessTokens', 'projectsOnly')}
              </label>
              {projects.isPending && (
                <span role="status" aria-label={t('personalAccessTokens', 'projectsLoading')}>
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" strokeWidth={1.5} />
                </span>
              )}
            </div>
          </RadioGroup>
        )}
      />
      {loaded?.length === 0 && <p className="text-[13px] text-muted-foreground">{t('personalAccessTokens', 'projectsEmpty')}</p>}
      {projects.isError && (
        <p className="flex items-center gap-2 text-[13px] text-destructive">
          {t('personalAccessTokens', 'projectsLoadError')}
          <Button type="button" size="xs" variant="ghost" onClick={() => void projects.refetch()}>
            {t('personalAccessTokens', 'retry')}
          </Button>
        </p>
      )}
      {mode === 'only' && canRestrict && (
        <FormField
          control={control}
          name="project_ids"
          render={({field}) => {
            const selected = field.value ?? [];
            const toggle = (id: string, checked: boolean) =>
              field.onChange(checked ? [...selected, id] : selected.filter((x) => x !== id));
            const outOfRange = selected.length === 0 || selected.length > MAX_PROJECTS;
            return (
              <FormItem className="space-y-0">
                <ul
                  role="group"
                  aria-label={t('personalAccessTokens', 'projectsOnly')}
                  className="mt-1 max-h-48 space-y-px overflow-y-auto"
                >
                  {loaded.map((project) => (
                    <li key={project.id}>
                      <label className="flex min-w-0 items-center gap-2 rounded-sm px-2 py-1 text-[13px] hover:bg-muted/50 [@media(pointer:coarse)]:min-h-11">
                        <Checkbox
                          checked={selected.includes(project.id)}
                          onCheckedChange={(checked) => toggle(project.id, checked === true)}
                        />
                        <span className="min-w-0 truncate" title={project.name}>{project.name}</span>
                      </label>
                    </li>
                  ))}
                </ul>
                <p
                  id={PROJECTS_COUNT_ID}
                  className={cn('mt-1 text-[12px]', outOfRange ? 'text-destructive' : 'text-muted-foreground')}
                >
                  {t('personalAccessTokens', 'projectsSelectedCount').replace('{{n}}', String(selected.length))}
                </p>
                <FormMessage className="text-[12px]" />
              </FormItem>
            );
          }}
        />
      )}
    </SettingsRow>
  );
}

function CreateDialog({
  open,
  onOpenChange,
  onCreated,
  create,
  projects,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (secret: string) => void;
  create: ReturnType<typeof useCreateMyToken>;
  projects: ProjectsQuery;
}) {
  const form = useForm<CreateValues>({mode: 'onChange', resolver: zodResolver(createSchema), defaultValues: CREATE_DEFAULTS});
  const [formError, setFormError] = useState<string | null>(null);
  const name = useWatch({control: form.control, name: 'name'});
  const aiRun = useWatch({control: form.control, name: 'ai_run'});
  const expiryOptions = aiRun ? AI_RUN_EXPIRY_OPTIONS : EXPIRY_OPTIONS;
  const mode = useWatch({control: form.control, name: 'projectMode'});
  const selectedCount = useWatch({control: form.control, name: 'project_ids'})?.length ?? 0;
  const projectsInvalid = mode === 'only' && (selectedCount === 0 || selectedCount > MAX_PROJECTS);

  // A project that left the list (a refused submit refetches it) leaves the selection too.
  const loadedProjects = projects.isSuccess ? projects.data : undefined;
  useEffect(() => {
    if (!loadedProjects) return;
    const known = new Set(loadedProjects.map((project) => project.id));
    const current = form.getValues('project_ids') ?? [];
    const kept = current.filter((id) => known.has(id));
    if (kept.length !== current.length) form.setValue('project_ids', kept, {shouldValidate: true});
  }, [loadedProjects, form]);

  const reset = () => {
    form.reset(CREATE_DEFAULTS);
    setFormError(null);
  };
  const cancel = () => {
    reset();
    onOpenChange(false);
  };
  const submit = ({name: tokenName, scope, expires_in_days, ai_run, projectMode, project_ids}: CreateValues) => {
    setFormError(null);
    create.mutate(
      {name: tokenName, scope, expires_in_days, ai_run, ...(projectMode === 'only' ? {project_ids} : {})},
      {
        onSuccess: (data) => {
          reset();
          onOpenChange(false);
          onCreated(data.secret);
        },
        onError: (error) => {
          setFormError(createErrorMessage(error));
          // A refused project left the list: reload it so the picker drops it.
          if (isProjectNotAccessibleError(error)) void projects.refetch();
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) cancel(); }}>
      <DialogContent size="md">
        <DialogHeader>
          <DialogTitle>{t('personalAccessTokens', 'createTitle')}</DialogTitle>
        </DialogHeader>
        <DialogBody>
          <Form {...form}>
            <form id="pat-create-form" className="space-y-1" onSubmit={form.handleSubmit(submit)}>
              <FormField
                control={form.control}
                name="name"
                render={({field}) => (
                  <FormItem className="space-y-0">
                    <SettingsRow label={t('personalAccessTokens', 'nameLabel')} htmlFor="pat-name">
                      <FormControl>
                        <Input id="pat-name" variant="quiet" {...field} placeholder={t('personalAccessTokens', 'namePlaceholder')} maxLength={80} />
                      </FormControl>
                      <FormMessage className="text-[12px]" />
                    </SettingsRow>
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="scope"
                render={({field}) => (
                  <SettingsRow label={t('personalAccessTokens', 'scopeLabel')} htmlFor="pat-scope">
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger id="pat-scope" variant="quiet">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="read">{t('personalAccessTokens', 'scopeRead')}</SelectItem>
                        <SelectItem value="read_write">{t('personalAccessTokens', 'scopeReadWrite')}</SelectItem>
                      </SelectContent>
                    </Select>
                  </SettingsRow>
                )}
              />
              <FormField
                control={form.control}
                name="expires_in_days"
                render={({field}) => (
                  <SettingsRow label={t('personalAccessTokens', 'expiryLabel')} htmlFor="pat-expiry">
                    <Select value={String(field.value)} onValueChange={(next) => field.onChange(Number(next))}>
                      <SelectTrigger id="pat-expiry" variant="quiet">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {expiryOptions.map((days) => (
                          <SelectItem key={days} value={String(days)}>{t('personalAccessTokens', 'expiryDays').replace('{{n}}', String(days))}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </SettingsRow>
                )}
              />
              <FormField
                control={form.control}
                name="ai_run"
                render={({field}) => (
                  <SettingsRow label={t('personalAccessTokens', 'aiRunRowLabel')} align="start">
                    <div className="flex items-start gap-2 py-1">
                      <Checkbox
                        id="pat-ai-run"
                        checked={field.value}
                        onCheckedChange={(checked) => {
                          const next = checked === true;
                          field.onChange(next);
                          if (next && form.getValues('expires_in_days') !== 30) form.setValue('expires_in_days', 30);
                        }}
                        aria-describedby="pat-ai-run-hint"
                        className="mt-0.5"
                      />
                      <div className="min-w-0 space-y-0.5">
                        <label htmlFor="pat-ai-run" className="text-[13px]">{t('personalAccessTokens', 'aiRunLabel')}</label>
                        <p id="pat-ai-run-hint" className="text-[12px] text-muted-foreground">{t('personalAccessTokens', 'aiRunHint')}</p>
                      </div>
                    </div>
                  </SettingsRow>
                )}
              />
              <ProjectsField control={form.control} projects={projects} />
              {formError && <p role="alert" className="text-[13px] text-destructive">{formError}</p>}
            </form>
          </Form>
        </DialogBody>
        <DialogFooter>
          <Button type="button" size="sm" variant="outline" onClick={cancel}>{t('personalAccessTokens', 'cancel')}</Button>
          <Button
            type="submit"
            form="pat-create-form"
            size="sm"
            disabled={create.isPending || name.trim() === '' || projectsInvalid}
            aria-describedby={projectsInvalid ? PROJECTS_COUNT_ID : undefined}
          >
            {create.isPending ? t('personalAccessTokens', 'creating') : t('personalAccessTokens', 'createSubmit')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function PersonalAccessTokensGroup() {
  const tokens = useMyTokens();
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const create = useCreateMyToken();
  const projects = useProjectsQuery();

  const closeReveal = () => {
    setSecret(null);
    create.reset();
  };

  const createButton = (
    <Button size="sm" variant="ghost" onClick={() => setCreating(true)} disabled={tokens.isPending}>
      <Plus className="mr-1 h-4 w-4" strokeWidth={1.5} />{t('personalAccessTokens', 'createButton')}
    </Button>
  );

  return (
    <SettingsGroup title={t('personalAccessTokens', 'groupTitle')} hint={t('personalAccessTokens', 'groupHint')}>
      <p className="text-[13px] text-muted-foreground">{t('personalAccessTokens', 'clientsNote')}</p>
      <p className="text-[13px] text-muted-foreground">{t('personalAccessTokens', 'readRecommendation')}</p>

      {tokens.isPending && (
        <ul className="space-y-1" aria-label={t('personalAccessTokens', 'listLoading')}>
          <li><Skeleton className="h-8 w-full" /></li>
          <li><Skeleton className="h-8 w-full" /></li>
        </ul>
      )}

      {tokens.isError && (
        <p className="flex items-center gap-2 text-[13px] text-destructive">
          {t('personalAccessTokens', 'listLoadError')}
          <Button size="sm" variant="ghost" onClick={() => void tokens.refetch()}>{t('personalAccessTokens', 'retry')}</Button>
        </p>
      )}

      {!tokens.isError && tokens.data && tokens.data.length === 0 && (
        <div className="flex items-center gap-3 text-[13px] text-muted-foreground">
          <span>{t('personalAccessTokens', 'listEmpty')}</span>
        </div>
      )}

      {!tokens.isError && tokens.data && tokens.data.length > 0 && (
        <TokenList rows={tokens.data} projects={projects} />
      )}

      {createButton}

      <CreateDialog open={creating} onOpenChange={setCreating} onCreated={setSecret} create={create} projects={projects} />

      <Dialog open={secret !== null} onOpenChange={() => {}}>
        <DialogContent
          size="md"
          showCloseButton={false}
          onEscapeKeyDown={(e) => e.preventDefault()}
          onInteractOutside={(e) => e.preventDefault()}
        >
          <DialogHeader>
            <DialogTitle>{t('personalAccessTokens', 'revealTitle')}</DialogTitle>
            <DialogDescription>{t('personalAccessTokens', 'revealWarning')}</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-3">
            {secret && <CopyBlock label={t('personalAccessTokens', 'tokenLabel')} code={secret} copyAriaLabel={t('personalAccessTokens', 'copyTokenAria')} />}
            {secret && <McpClientSnippetSelector token={secret} clients={TOKEN_CLIENT_IDS} />}
          </DialogBody>
          <DialogFooter>
            <Button size="sm" onClick={closeReveal}>{t('personalAccessTokens', 'revealDone')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SettingsGroup>
  );
}
