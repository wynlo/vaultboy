import React from 'react';
import ReactDOM from 'react-dom/client';
import { BriefcaseBusiness, ChevronDown, ChevronRight, Cloud, Download, Edit3, Eye, FolderOpen, GitBranch, Loader2, Moon, Play, Power, RefreshCw, Save, ScrollText, ShieldCheck, Smartphone, Sun, TestTube2, Upload, X } from 'lucide-react';
import { Badge } from './components/ui/badge';
import { Button } from './components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './components/ui/card';
import { Input } from './components/ui/input';
import './styles.css';

type Project = {
  name: string;
  repoVaultPath: string;
  icloudVaultPath: string;
  enabled: boolean;
  propagateDeletes: boolean;
  repoExists: boolean;
  icloudExists: boolean;
  repoFileCount: number;
  icloudFileCount: number;
  lastSyncTime: string | null;
  status: string;
  conflictCount: number;
};

type FormState = {
  name: string;
  repoVaultPath: string;
  icloudVaultPath: string;
  enabled: boolean;
  propagateDeletes: boolean;
};

type Job = {
  id: string;
  project: string;
  mode: string;
  dryRun: boolean;
  trigger: string;
  startedAt: string;
  finishedAt: string | null;
  durationMs: number | null;
  status: string;
  copiedCount: number;
  conflictCount: number;
  errorCount: number;
  copied: string[];
  conflicts: string[];
  errors: string[];
};

type AppStatus = {
  intervalSeconds: number;
  scheduler: {
    running: boolean;
    nextRunAt: string | null;
    trackedJobs: number;
  };
};

type CompareResult = {
  project: string;
  repoFileCount: number;
  icloudFileCount: number;
  repoDirCount: number;
  icloudDirCount: number;
  filesOnlyInRepo: string[];
  filesOnlyInIcloud: string[];
  dirsOnlyInRepo: string[];
  dirsOnlyInIcloud: string[];
  commonDifferent: string[];
};

const emptyForm: FormState = { name: '', repoVaultPath: '', icloudVaultPath: '', enabled: true, propagateDeletes: true };
const jobsPerPage = 5;

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json() as Promise<T>;
}

function App() {
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [form, setForm] = React.useState<FormState>(emptyForm);
  const [editingName, setEditingName] = React.useState<string | null>(null);
  const [logs, setLogs] = React.useState('Select View logs on a project.');
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [jobs, setJobs] = React.useState<Job[]>([]);
  const [status, setStatus] = React.useState<AppStatus | null>(null);
  const [darkMode, setDarkMode] = React.useState(() => localStorage.getItem('vaultboy-theme') === 'dark');
  const [icloudOverridden, setIcloudOverridden] = React.useState(false);
  const [jobPage, setJobPage] = React.useState(1);
  const [compare, setCompare] = React.useState<CompareResult | null>(null);

  const loadProjects = React.useCallback(async (showLoading = false) => {
    if (showLoading) {
      setLoading(true);
    }
    try {
      const [nextProjects, nextJobs, nextStatus] = await Promise.all([
        request<Project[]>('/api/projects'),
        request<Job[]>('/api/jobs'),
        request<AppStatus>('/api/status'),
      ]);
      setProjects(nextProjects);
      setJobs(nextJobs);
      setStatus(nextStatus);
    } catch (error) {
      setLogs(`Error: ${(error as Error).message}`);
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  }, []);

  React.useEffect(() => {
    void loadProjects(true);
  }, [loadProjects]);

  React.useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(jobs.length / jobsPerPage));
    if (jobPage > maxPage) {
      setJobPage(maxPage);
    }
  }, [jobPage, jobs.length]);

  React.useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode);
    localStorage.setItem('vaultboy-theme', darkMode ? 'dark' : 'light');
  }, [darkMode]);

  React.useEffect(() => {
    if (icloudOverridden || editingName || (!form.name.trim() && !form.repoVaultPath.trim())) {
      return;
    }
    let cancelled = false;
    const params = new URLSearchParams({ name: form.name, repoVaultPath: form.repoVaultPath });
    request<{ path: string }>(`/api/suggest-icloud-path?${params.toString()}`)
      .then((result) => {
        if (!cancelled && result.path) {
          setForm((current) => ({ ...current, icloudVaultPath: result.path }));
        }
      })
      .catch((error) => setLogs(`Error: ${(error as Error).message}`));
    return () => {
      cancelled = true;
    };
  }, [editingName, form.name, form.repoVaultPath, icloudOverridden]);

  async function saveProject(event: React.FormEvent) {
    event.preventDefault();
    setBusy('save');
    try {
      const path = editingName ? `/api/projects/${encodeURIComponent(editingName)}` : '/api/projects';
      const method = editingName ? 'PUT' : 'POST';
      await request<Project>(path, { method, body: JSON.stringify(form) });
      setForm(emptyForm);
      setEditingName(null);
      setIcloudOverridden(false);
      await loadProjects();
    } catch (error) {
      setLogs(`Error: ${(error as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  async function action(project: Project, endpoint: string) {
    if (endpoint === 'edit') {
      setEditingName(project.name);
      setForm({ name: project.name, repoVaultPath: project.repoVaultPath, icloudVaultPath: project.icloudVaultPath, enabled: project.enabled, propagateDeletes: project.propagateDeletes });
      setIcloudOverridden(true);
      window.scrollTo({ top: 0, behavior: 'smooth' });
      return;
    }
    setBusy(`${project.name}:${endpoint}`);
    try {
      if (endpoint === 'logs') {
        const result = await request<{ logs: string[] }>(`/api/projects/${encodeURIComponent(project.name)}/logs`);
        setLogs(result.logs.join('\n') || 'No logs for this project yet.');
        return;
      }
      if (endpoint === 'compare') {
        const result = await request<CompareResult>(`/api/projects/${encodeURIComponent(project.name)}/compare`);
        setCompare(result);
        return;
      }
      const finalEndpoint = endpoint === 'toggle' ? (project.enabled ? 'disable' : 'enable') : endpoint;
      const result = await request<Record<string, unknown>>(`/api/projects/${encodeURIComponent(project.name)}/${finalEndpoint}`, { method: 'POST' });
      setLogs(JSON.stringify(result, null, 2));
      await loadProjects();
    } catch (error) {
      setLogs(`Error: ${(error as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  const totalJobPages = Math.max(1, Math.ceil(jobs.length / jobsPerPage));
  const visibleJobs = jobs.slice((jobPage - 1) * jobsPerPage, jobPage * jobsPerPage);

  async function pickRepoPath() {
    setBusy('pick-folder');
    try {
      const result = await request<{ path: string | null }>('/api/pick-folder', { method: 'POST' });
      if (result.path) {
        setForm((current) => ({ ...current, repoVaultPath: result.path }));
      }
    } catch (error) {
      setLogs(`Error: ${(error as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="mx-auto grid min-h-screen w-full min-w-0 max-w-5xl gap-5 overflow-x-hidden px-4 py-5 sm:px-6 lg:px-8">
      <div className="flex justify-end">
        <Button variant="outline" onClick={() => setDarkMode((value) => !value)} aria-pressed={darkMode}>
          {darkMode ? <Sun size={18} /> : <Moon size={18} />}
          {darkMode ? 'Light mode' : 'Dark mode'}
        </Button>
      </div>

      <CollapsibleSection title="Overview" defaultOpen>
        <div className="grid gap-4">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">local obsidian sync</p>
          <div className="flex items-center gap-3">
            <img className="h-12 w-12 rounded-2xl border bg-background sm:h-16 sm:w-16" src="/icons/vaultboy.svg" alt="" aria-hidden="true" />
            <h1 className="max-w-2xl text-4xl font-semibold tracking-tight text-foreground sm:text-6xl">Vaultboy</h1>
          </div>
          <p className="max-w-2xl text-lg text-muted-foreground">Sync project docs vaults with the iCloud Obsidian folder used by Obsidian iOS.</p>
          <div className="rounded-md border bg-background p-3 text-sm text-muted-foreground">
            Scheduler: <strong className="text-foreground">{status?.scheduler.running ? 'running' : 'unknown'}</strong> | Interval: <strong className="text-foreground">{status?.intervalSeconds ?? 300}s</strong> | Next auto-sync: <strong className="text-foreground">{formatDate(status?.scheduler.nextRunAt)}</strong>
          </div>
          <div className="grid min-w-0 gap-3 sm:grid-cols-3">
            <InfoPill icon={<Smartphone size={18} />} label="iPhone" value="iCloud Drive/Obsidian/<vault-name>" />
            <InfoPill icon={<Cloud size={18} />} label="macOS" value="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/<vault-name>" />
            <InfoPill icon={<ShieldCheck size={18} />} label="Deletes" value="Propagates unchanged synced deletes by default" />
          </div>
        </div>
      </CollapsibleSection>

      <CollapsibleSection title={editingName ? 'Edit Project' : 'Add Project'} description="Map one repo docs vault to its matching iCloud Obsidian vault." defaultOpen>
          <form className="grid gap-4" onSubmit={saveProject}>
            <Field label="Project name" value={form.name} onChange={(value) => setForm({ ...form, name: value })} placeholder="example-project" />
            <Field
              label="Repo docs path"
              value={form.repoVaultPath}
              onChange={(value) => setForm({ ...form, repoVaultPath: value })}
              placeholder="/Users/me/Projects/example/docs"
              action={<Button type="button" variant="outline" onClick={pickRepoPath} disabled={busy === 'pick-folder'}>{busy === 'pick-folder' ? <Loader2 className="animate-spin" size={18} /> : <FolderOpen size={18} />} Browse</Button>}
            />
            <Field
              label="iCloud vault path"
              value={form.icloudVaultPath}
              onChange={(value) => { setIcloudOverridden(true); setForm({ ...form, icloudVaultPath: value }); }}
              placeholder="/Users/me/Library/Mobile Documents/iCloud~md~obsidian/Documents/example-project"
              hint="Auto-filled from project name or repo folder. Edit this field to override."
            />
            <label className="flex items-center gap-3 text-sm font-medium text-muted-foreground">
              <input className="h-5 w-5 accent-primary" type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />
              Enabled
            </label>
            <label className="flex items-start gap-3 text-sm font-medium text-muted-foreground">
              <input className="mt-0.5 h-5 w-5 accent-primary" type="checkbox" checked={form.propagateDeletes} onChange={(event) => setForm({ ...form, propagateDeletes: event.target.checked })} />
              <span><span className="text-foreground">Propagate deletes</span><br /><span className="text-xs font-normal">On by default. Delete unchanged synced files from the other side when removed here.</span></span>
            </label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button size="lg" type="submit" disabled={busy === 'save'}>{busy === 'save' ? <Loader2 className="animate-spin" size={18} /> : <Save size={18} />} Save Project</Button>
              {editingName && <Button type="button" variant="outline" size="lg" onClick={() => { setEditingName(null); setIcloudOverridden(false); setForm(emptyForm); }}><X size={18} /> Cancel Edit</Button>}
            </div>
          </form>
      </CollapsibleSection>

      <CollapsibleSection
        title="Projects"
        defaultOpen
        action={<Button type="button" variant="outline" onClick={() => void loadProjects()} disabled={busy === 'refresh'}><RefreshCw size={18} />Refresh</Button>}
      >
        {loading ? <Card><CardContent className="p-5 text-muted-foreground">Loading projects...</CardContent></Card> : null}
        {!loading && projects.length === 0 ? <Card><CardContent className="p-5 text-muted-foreground">No projects configured yet.</CardContent></Card> : null}
        {projects.map((project) => <ProjectCard key={project.name} project={project} busy={busy} onAction={action} />)}
      </CollapsibleSection>

      <CollapsibleSection title="Cleanup Compare" description="Shows current repo/iCloud drift. Prune actions are dry-run only from the UI for now." defaultOpen={false}>
        {compare ? <ComparePanel compare={compare} setLogs={setLogs} /> : <p className="text-sm text-muted-foreground">Click Compare on a project to inspect repo vs iCloud differences.</p>}
      </CollapsibleSection>

      <CollapsibleSection title="Sync Jobs" description="Recent auto and manual sync attempts from this running Vaultboy process." icon={<BriefcaseBusiness size={20} />} defaultOpen>
          <div className="grid gap-3">
            {jobs.length === 0 ? <p className="text-sm text-muted-foreground">No sync jobs recorded since this process started.</p> : null}
            {visibleJobs.map((job) => <JobCard key={job.id} job={job} />)}
            {jobs.length > jobsPerPage ? (
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-sm text-muted-foreground">Page {jobPage} of {totalJobPages} | {jobs.length} jobs</p>
                <div className="flex gap-2">
                  <Button type="button" variant="outline" disabled={jobPage <= 1} onClick={() => setJobPage((page) => Math.max(1, page - 1))}>Previous</Button>
                  <Button type="button" variant="outline" disabled={jobPage >= totalJobPages} onClick={() => setJobPage((page) => Math.min(totalJobPages, page + 1))}>Next</Button>
                </div>
              </div>
            ) : null}
          </div>
      </CollapsibleSection>

      <CollapsibleSection title="Logs" icon={<ScrollText size={20} />} defaultOpen>
          <pre className="max-h-[420px] min-w-0 overflow-auto whitespace-pre-wrap break-all rounded-md border bg-muted p-4 text-xs text-foreground [overflow-wrap:anywhere]">{logs}</pre>
      </CollapsibleSection>
    </main>
  );
}

function CollapsibleSection({ title, description, icon, action, defaultOpen = false, cardClassName, children }: { title: string; description?: string; icon?: React.ReactNode; action?: React.ReactNode; defaultOpen?: boolean; cardClassName?: string; children: React.ReactNode }) {
  const [open, setOpen] = React.useState(defaultOpen);
  return (
    <Card className={cardClassName}>
      <CardHeader>
        <div className="flex min-w-0 items-start justify-between gap-3">
          <button type="button" className="flex min-w-0 flex-1 items-start gap-2 text-left" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
            {open ? <ChevronDown className="mt-1 shrink-0" size={18} /> : <ChevronRight className="mt-1 shrink-0" size={18} />}
            <div className="min-w-0">
              <CardTitle className="flex items-center gap-2">{icon}{title}</CardTitle>
              {description ? <CardDescription>{description}</CardDescription> : null}
            </div>
          </button>
          {action ? <div className="shrink-0" onClick={(event) => event.stopPropagation()}>{action}</div> : null}
        </div>
      </CardHeader>
      {open ? <CardContent className="grid gap-4">{children}</CardContent> : null}
    </Card>
  );
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return 'not scheduled yet';
  }
  return new Date(value).toLocaleString();
}

function JobCard({ job }: { job: Job }) {
  const details = [...job.errors, ...job.conflicts, ...job.copied].slice(0, 6);
  return (
    <div className="grid gap-2 rounded-md border bg-background p-4 text-sm">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="font-semibold text-foreground">{job.project} | {job.mode}{job.dryRun ? ' | dry run' : ''}</div>
          <div className="text-muted-foreground">{job.trigger} | started {formatDate(job.startedAt)} | {job.durationMs === null ? 'running' : `${job.durationMs}ms`}</div>
        </div>
        <Badge className="w-fit shrink-0" status={job.status} />
      </div>
      <div className="text-muted-foreground">Copied {job.copiedCount} | Conflicts {job.conflictCount} | Errors {job.errorCount}</div>
      {details.length ? <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-all rounded-md border bg-muted p-3 text-xs [overflow-wrap:anywhere]">{details.join('\n')}</pre> : null}
    </div>
  );
}

function ComparePanel({ compare, setLogs }: { compare: CompareResult; setLogs: (value: string) => void }) {
  async function dryRun(side: 'repo' | 'icloud', paths: string[]) {
    const result = await request<Record<string, unknown>>(`/api/projects/${encodeURIComponent(compare.project)}/prune`, {
      method: 'POST',
      body: JSON.stringify({ side, paths, dryRun: true }),
    });
    setLogs(JSON.stringify(result, null, 2));
  }

  return (
    <div className="grid gap-4">
      <div className="rounded-md border bg-background p-4 text-sm text-muted-foreground">
        <strong className="text-foreground">{compare.project}</strong> | repo {compare.repoFileCount} files / {compare.repoDirCount} dirs | iCloud {compare.icloudFileCount} files / {compare.icloudDirCount} dirs
      </div>
      <DiffList title="Files only in repo" items={compare.filesOnlyInRepo} actionLabel="Dry-run prune repo" onAction={() => dryRun('repo', compare.filesOnlyInRepo)} />
      <DiffList title="Files only in iCloud" items={compare.filesOnlyInIcloud} actionLabel="Dry-run prune iCloud" onAction={() => dryRun('icloud', compare.filesOnlyInIcloud)} />
      <DiffList title="Dirs only in repo" items={compare.dirsOnlyInRepo} />
      <DiffList title="Dirs only in iCloud" items={compare.dirsOnlyInIcloud} />
      <DiffList title="Different on both sides" items={compare.commonDifferent} />
    </div>
  );
}

function DiffList({ title, items, actionLabel, onAction }: { title: string; items: string[]; actionLabel?: string; onAction?: () => void }) {
  return (
    <div className="grid gap-2 rounded-md border bg-background p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h3 className="font-semibold">{title} ({items.length})</h3>
        {actionLabel && items.length ? <Button type="button" variant="outline" onClick={onAction}>{actionLabel}</Button> : null}
      </div>
      {items.length ? <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-md border bg-muted p-3 text-xs [overflow-wrap:anywhere]">{items.join('\n')}</pre> : <p className="text-sm text-muted-foreground">None</p>}
    </div>
  );
}

function InfoPill({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return <div className="min-w-0 rounded-md border bg-background p-4"><div className="mb-2 flex min-w-0 items-center gap-2 text-sm font-semibold text-foreground">{icon}{label}</div><div className="break-all text-sm text-muted-foreground [overflow-wrap:anywhere]">{value}</div></div>;
}

function Field({ label, value, onChange, placeholder, action, hint }: { label: string; value: string; onChange: (value: string) => void; placeholder: string; action?: React.ReactNode; hint?: string }) {
  return (
    <label className="grid gap-2 text-sm font-medium text-muted-foreground">
      {label}
      <div className="flex min-w-0 flex-col gap-2 sm:flex-row">
        <Input required value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
        {action}
      </div>
      {hint ? <span className="text-xs font-normal text-muted-foreground">{hint}</span> : null}
    </label>
  );
}

function ProjectCard({ project, busy, onAction }: { project: Project; busy: string | null; onAction: (project: Project, endpoint: string) => void }) {
  const isBusy = (endpoint: string) => busy === `${project.name}:${endpoint}`;
  return (
    <Card>
      <CardHeader>
        <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <CardTitle className="flex min-w-0 items-center gap-2 break-all [overflow-wrap:anywhere]"><GitBranch className="shrink-0" size={20} />{project.name}</CardTitle>
            <CardDescription>Last sync: {project.lastSyncTime || 'Never'}</CardDescription>
          </div>
          <Badge className="w-fit shrink-0" status={project.status} />
        </div>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid min-w-0 gap-2 text-sm text-muted-foreground">
          <div className="break-all [overflow-wrap:anywhere]"><strong className="text-foreground">Repo:</strong> {project.repoVaultPath}</div>
          <div className="break-all [overflow-wrap:anywhere]"><strong className="text-foreground">iCloud:</strong> {project.icloudVaultPath}</div>
          <div><strong className="text-foreground">Exists:</strong> repo {project.repoExists ? 'yes' : 'no'} | iCloud {project.icloudExists ? 'yes' : 'no'}</div>
          <div><strong className="text-foreground">Files:</strong> repo {project.repoFileCount} | iCloud {project.icloudFileCount}</div>
          <div><strong className="text-foreground">Delete propagation:</strong> {project.propagateDeletes ? 'on' : 'off'}</div>
          <div><strong className="text-foreground">Conflicts:</strong> {project.conflictCount || 0}</div>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <Button onClick={() => onAction(project, 'sync')} disabled={isBusy('sync')}><Play size={18} />Sync now</Button>
          <Button variant="secondary" onClick={() => onAction(project, 'pull')} disabled={isBusy('pull')}><Download size={18} />Pull from iCloud</Button>
          <Button variant="secondary" onClick={() => onAction(project, 'push')} disabled={isBusy('push')}><Upload size={18} />Push to iCloud</Button>
          <Button variant="outline" onClick={() => onAction(project, 'dry-run')} disabled={isBusy('dry-run')}><TestTube2 size={18} />Dry run</Button>
          <Button variant="outline" onClick={() => onAction(project, 'compare')} disabled={isBusy('compare')}><Eye size={18} />Compare</Button>
          <Button variant="outline" onClick={() => onAction(project, 'logs')}><Eye size={18} />View logs</Button>
          <Button variant={project.enabled ? 'destructive' : 'default'} onClick={() => onAction(project, 'toggle')}><Power size={18} />{project.enabled ? 'Disable' : 'Enable'}</Button>
          <Button variant="ghost" onClick={() => onAction(project, 'edit')}><Edit3 size={18} />Edit</Button>
        </div>
      </CardContent>
    </Card>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(<App />);
