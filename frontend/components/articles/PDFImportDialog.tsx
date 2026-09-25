/**
 * Dialog for importing an article from a PDF file.
 *
 * Flow:
 * 1. User selects a PDF file
 * 2. PDF is uploaded to Supabase Storage
 * 3. Backend extracts metadata via AI (OpenAI Responses API)
 * 4. User reviews extracted metadata in a form
 * 5. Article is created with metadata + linked PDF
 */

import {useCallback, useState} from 'react';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {Label} from '@/components/ui/label';
import {Textarea} from '@/components/ui/textarea';
import {ScrollArea} from '@/components/ui/scroll-area';
import {Badge} from '@/components/ui/badge';
import {Brain, CheckCircle2, FileUp, Loader2, Upload} from 'lucide-react';
import {supabase} from '@/integrations/supabase/client';
import {toast} from 'sonner';
import {t} from '@/lib/copy';
import {validateFile} from '@/lib/file-validation';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';

interface ExtractedMetadata {
    title: string | null;
    abstract: string | null;
    authors: string[] | null;
    publicationYear: number | null;
    publicationMonth: number | null;
    journalTitle: string | null;
    journalIssn: string | null;
    volume: string | null;
    issue: string | null;
    pages: string | null;
    doi: string | null;
    pmid: string | null;
    pmcid: string | null;
    keywords: string[] | null;
    articleType: string | null;
    language: string | null;
    urlLanding: string | null;
    studyDesign: string | null;
}

interface PDFImportDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    projectId: string;
    onImportComplete?: () => void;
}

type Step = 'upload' | 'extracting' | 'review' | 'saving';

export function PDFImportDialog({
    open,
    onOpenChange,
    projectId,
    onImportComplete,
}: PDFImportDialogProps) {
    const [step, setStep] = useState<Step>('upload');
    const [pdfFile, setPdfFile] = useState<File | null>(null);
    const [storageKey, setStorageKey] = useState<string | null>(null);
    const [metadata, setMetadata] = useState<ExtractedMetadata | null>(null);
    const [error, setError] = useState<string | null>(null);

    // Editable form state (populated from AI extraction)
    const [formData, setFormData] = useState({
        title: '',
        abstract: '',
        authors: '',
        publication_year: '',
        publication_month: '',
        journal_title: '',
        journal_issn: '',
        volume: '',
        issue: '',
        pages: '',
        doi: '',
        pmid: '',
        pmcid: '',
        keywords: '',
        article_type: '',
        language: '',
        url_landing: '',
        study_design: '',
    });

    const reset = useCallback(() => {
        setStep('upload');
        setPdfFile(null);
        setStorageKey(null);
        setMetadata(null);
        setError(null);
        setFormData({
            title: '', abstract: '', authors: '', publication_year: '',
            publication_month: '', journal_title: '', journal_issn: '',
            volume: '', issue: '', pages: '', doi: '', pmid: '', pmcid: '',
            keywords: '', article_type: '', language: '', url_landing: '',
            study_design: '',
        });
    }, []);

    const populateForm = (m: ExtractedMetadata) => {
        setFormData({
            title: m.title || '',
            abstract: m.abstract || '',
            authors: m.authors?.join(', ') || '',
            publication_year: m.publicationYear?.toString() || '',
            publication_month: m.publicationMonth?.toString() || '',
            journal_title: m.journalTitle || '',
            journal_issn: m.journalIssn || '',
            volume: m.volume || '',
            issue: m.issue || '',
            pages: m.pages || '',
            doi: m.doi || '',
            pmid: m.pmid || '',
            pmcid: m.pmcid || '',
            keywords: m.keywords?.join(', ') || '',
            article_type: m.articleType || '',
            language: m.language || '',
            url_landing: m.urlLanding || '',
            study_design: m.studyDesign || '',
        });
    };

    const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        e.target.value = '';
        if (!file) return;

        const validation = validateFile(file);
        if (!validation.valid) {
            setError(validation.error || 'Invalid file');
            return;
        }

        setPdfFile(file);
        setError(null);
        setStep('extracting');

        try {
            const {data: {session}} = await supabase.auth.getSession();
            if (!session?.access_token) {
                throw new Error('Authentication required');
            }

            // Step 1: Upload PDF to the user's temporary area of Supabase Storage.
            // The backend only accepts keys under temp/{userId}/ and moves the
            // file to its permanent path when the article is created.
            const tempId = crypto.randomUUID();
            const fileExt = file.name.split('.').pop();
            const key = `temp/${session.user.id}/${tempId}/${Date.now()}.${fileExt}`;

            const {error: uploadError} = await supabase.storage
                .from('articles')
                .upload(key, file);

            if (uploadError) {
                throw new Error(`Upload failed: ${uploadError.message}`);
            }
            setStorageKey(key);

            // Step 2: Call backend to extract metadata via AI
            const formPayload = new FormData();
            formPayload.append('project_id', projectId);
            formPayload.append('storage_key', key);
            formPayload.append('original_filename', file.name);

            const response = await fetch(`${API_BASE_URL}/api/v1/article-import/pdf-extract-metadata`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${session.access_token}`,
                },
                body: formPayload,
            });

            const result = await response.json();

            if (!result.ok) {
                throw new Error(result.error?.message || 'Metadata extraction failed');
            }

            const extracted: ExtractedMetadata = result.data.metadata;
            setMetadata(extracted);
            populateForm(extracted);
            setStep('review');
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Unknown error';
            setError(message);
            setStep('upload');

            // Cleanup uploaded file on failure
            if (storageKey) {
                await supabase.storage.from('articles').remove([storageKey]);
                setStorageKey(null);
            }
        }
    };

    const handleSave = async () => {
        if (!formData.title.trim()) {
            toast.error(t('articles', 'titleRequiredToast'));
            return;
        }
        if (!storageKey || !pdfFile) {
            toast.error('No PDF file uploaded');
            return;
        }

        setStep('saving');

        try {
            const parseDateValue = (value: string): number | null => {
                if (!value.trim()) return null;
                const num = parseInt(value.trim(), 10);
                return isNaN(num) ? null : num;
            };

            const {data: {session}} = await supabase.auth.getSession();
            if (!session?.access_token) {
                throw new Error('Authentication required');
            }

            const payload = {
                projectId: projectId,
                storageKey: storageKey,
                originalFilename: pdfFile.name,
                fileBytes: pdfFile.size,
                title: formData.title.trim(),
                abstract: formData.abstract.trim() || null,
                authors: formData.authors.trim()
                    ? formData.authors.split(',').map(a => a.trim())
                    : null,
                publicationYear: parseDateValue(formData.publication_year),
                publicationMonth: parseDateValue(formData.publication_month),
                journalTitle: formData.journal_title.trim() || null,
                journalIssn: formData.journal_issn.trim() || null,
                volume: formData.volume.trim() || null,
                issue: formData.issue.trim() || null,
                pages: formData.pages.trim() || null,
                doi: formData.doi.trim() || null,
                pmid: formData.pmid.trim() || null,
                pmcid: formData.pmcid.trim() || null,
                keywords: formData.keywords.trim()
                    ? formData.keywords.split(',').map(k => k.trim())
                    : null,
                articleType: formData.article_type.trim() || null,
                language: formData.language.trim() || null,
                urlLanding: formData.url_landing.trim() || null,
                studyDesign: formData.study_design.trim() || null,
            };

            const response = await fetch(`${API_BASE_URL}/api/v1/article-import/pdf-create-article`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${session.access_token}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            });

            const result = await response.json();

            if (!result.ok) {
                throw new Error(result.error?.message || 'Failed to create article');
            }

            toast.success(t('articles', 'articleCreatedSuccess'));
            onImportComplete?.();
            onOpenChange(false);
            reset();
        } catch (err) {
            const message = err instanceof Error ? err.message : 'Unknown error';
            toast.error(message);
            setStep('review');
        }
    };

    const handleOpenChange = (next: boolean) => {
        if (!next && step !== 'upload') {
            if (window.confirm('Closing will discard the extracted data. Continue?')) {
                // Cleanup uploaded file
                if (storageKey) {
                    supabase.storage.from('articles').remove([storageKey]);
                }
                reset();
                onOpenChange(false);
            }
            return;
        }
        if (!next) reset();
        onOpenChange(next);
    };

    const updateField = (field: string, value: string) => {
        setFormData(prev => ({...prev, [field]: value}));
    };

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <DialogContent className="max-w-3xl max-h-[90vh] overflow-hidden flex flex-col">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Brain className="h-5 w-5"/>
                        Import from PDF (AI extraction)
                    </DialogTitle>
                    <DialogDescription>
                        Upload a PDF and AI will extract the bibliographic metadata automatically.
                    </DialogDescription>
                </DialogHeader>

                {/* Step: Upload */}
                {step === 'upload' && (
                    <div className="space-y-4 py-4">
                        <div className="flex flex-col items-center justify-center gap-4 rounded-lg border-2 border-dashed border-border/50 p-8 hover:border-border transition-colors">
                            <FileUp className="h-10 w-10 text-muted-foreground/50"/>
                            <div className="text-center">
                                <p className="text-sm font-medium">Select a PDF file</p>
                                <p className="text-xs text-muted-foreground mt-1">
                                    AI will extract title, authors, abstract, DOI and more
                                </p>
                            </div>
                            <input
                                type="file"
                                accept="application/pdf"
                                onChange={handleFileSelect}
                                className="hidden"
                                id="pdf-import-input"
                            />
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => document.getElementById('pdf-import-input')?.click()}
                            >
                                <Upload className="h-4 w-4 mr-2"/>
                                Select PDF
                            </Button>
                        </div>
                        {error && (
                            <p className="text-sm text-destructive" role="alert">{error}</p>
                        )}
                    </div>
                )}

                {/* Step: Extracting */}
                {step === 'extracting' && (
                    <div className="flex flex-col items-center justify-center gap-4 py-12">
                        <Loader2 className="h-8 w-8 animate-spin text-primary"/>
                        <div className="text-center">
                            <p className="text-sm font-medium">Extracting metadata from PDF...</p>
                            <p className="text-xs text-muted-foreground mt-1">
                                {pdfFile?.name} ({((pdfFile?.size || 0) / 1024 / 1024).toFixed(1)} MB)
                            </p>
                        </div>
                    </div>
                )}

                {/* Step: Review */}
                {step === 'review' && (
                    <ScrollArea className="flex-1 max-h-[60vh] pr-4">
                        <div className="space-y-4 py-2">
                            <div className="flex items-center gap-2 text-xs text-muted-foreground bg-muted/30 rounded-md px-3 py-2">
                                <CheckCircle2 className="h-3.5 w-3.5 text-green-500"/>
                                Metadata extracted from <span className="font-medium">{pdfFile?.name}</span>. Review and edit before saving.
                            </div>

                            <div>
                                <Label htmlFor="pdf-title">{t('articles', 'titleRequired')}</Label>
                                <Input
                                    id="pdf-title"
                                    value={formData.title}
                                    onChange={(e) => updateField('title', e.target.value)}
                                    placeholder={t('articles', 'titlePlaceholder')}
                                />
                            </div>

                            <div>
                                <Label htmlFor="pdf-abstract">{t('articles', 'abstract')}</Label>
                                <Textarea
                                    id="pdf-abstract"
                                    value={formData.abstract}
                                    onChange={(e) => updateField('abstract', e.target.value)}
                                    rows={3}
                                />
                            </div>

                            <div>
                                <Label htmlFor="pdf-authors">{t('articles', 'authors')}</Label>
                                <Input
                                    id="pdf-authors"
                                    value={formData.authors}
                                    onChange={(e) => updateField('authors', e.target.value)}
                                    placeholder={t('articles', 'authorsPlaceholder')}
                                />
                            </div>

                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <Label htmlFor="pdf-year">{t('articles', 'publicationYear')}</Label>
                                    <Input
                                        id="pdf-year"
                                        type="number"
                                        value={formData.publication_year}
                                        onChange={(e) => updateField('publication_year', e.target.value)}
                                    />
                                </div>
                                <div>
                                    <Label htmlFor="pdf-month">{t('articles', 'publicationMonth')}</Label>
                                    <Input
                                        id="pdf-month"
                                        type="number"
                                        value={formData.publication_month}
                                        onChange={(e) => updateField('publication_month', e.target.value)}
                                    />
                                </div>
                            </div>

                            <div>
                                <Label htmlFor="pdf-journal">{t('articles', 'journalTitle')}</Label>
                                <Input
                                    id="pdf-journal"
                                    value={formData.journal_title}
                                    onChange={(e) => updateField('journal_title', e.target.value)}
                                />
                            </div>

                            <div className="grid grid-cols-3 gap-4">
                                <div>
                                    <Label htmlFor="pdf-volume">Volume</Label>
                                    <Input
                                        id="pdf-volume"
                                        value={formData.volume}
                                        onChange={(e) => updateField('volume', e.target.value)}
                                    />
                                </div>
                                <div>
                                    <Label htmlFor="pdf-issue">{t('articles', 'issue')}</Label>
                                    <Input
                                        id="pdf-issue"
                                        value={formData.issue}
                                        onChange={(e) => updateField('issue', e.target.value)}
                                    />
                                </div>
                                <div>
                                    <Label htmlFor="pdf-pages">{t('articles', 'pages')}</Label>
                                    <Input
                                        id="pdf-pages"
                                        value={formData.pages}
                                        onChange={(e) => updateField('pages', e.target.value)}
                                    />
                                </div>
                            </div>

                            <div className="grid grid-cols-3 gap-4">
                                <div>
                                    <Label htmlFor="pdf-doi">DOI</Label>
                                    <Input
                                        id="pdf-doi"
                                        value={formData.doi}
                                        onChange={(e) => updateField('doi', e.target.value)}
                                    />
                                </div>
                                <div>
                                    <Label htmlFor="pdf-pmid">PMID</Label>
                                    <Input
                                        id="pdf-pmid"
                                        value={formData.pmid}
                                        onChange={(e) => updateField('pmid', e.target.value)}
                                    />
                                </div>
                                <div>
                                    <Label htmlFor="pdf-pmcid">PMCID</Label>
                                    <Input
                                        id="pdf-pmcid"
                                        value={formData.pmcid}
                                        onChange={(e) => updateField('pmcid', e.target.value)}
                                    />
                                </div>
                            </div>

                            <div>
                                <Label htmlFor="pdf-keywords">{t('articles', 'keywords')}</Label>
                                <Input
                                    id="pdf-keywords"
                                    value={formData.keywords}
                                    onChange={(e) => updateField('keywords', e.target.value)}
                                    placeholder={t('articles', 'keywordsPlaceholder')}
                                />
                            </div>

                            <div className="grid grid-cols-3 gap-4">
                                <div>
                                    <Label htmlFor="pdf-type">Type</Label>
                                    <Input
                                        id="pdf-type"
                                        value={formData.article_type}
                                        onChange={(e) => updateField('article_type', e.target.value)}
                                    />
                                </div>
                                <div>
                                    <Label htmlFor="pdf-lang">{t('articles', 'languageLabel')}</Label>
                                    <Input
                                        id="pdf-lang"
                                        value={formData.language}
                                        onChange={(e) => updateField('language', e.target.value)}
                                    />
                                </div>
                                <div>
                                    <Label htmlFor="pdf-design">{t('articles', 'studyDesignLabel')}</Label>
                                    <Input
                                        id="pdf-design"
                                        value={formData.study_design}
                                        onChange={(e) => updateField('study_design', e.target.value)}
                                    />
                                </div>
                            </div>
                        </div>
                    </ScrollArea>
                )}

                {/* Step: Saving */}
                {step === 'saving' && (
                    <div className="flex flex-col items-center justify-center gap-4 py-12">
                        <Loader2 className="h-8 w-8 animate-spin text-primary"/>
                        <p className="text-sm font-medium">{t('articles', 'saving')}</p>
                    </div>
                )}

                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={() => handleOpenChange(false)}
                        disabled={step === 'extracting' || step === 'saving'}
                    >
                        {t('common', 'cancel')}
                    </Button>
                    {step === 'review' && (
                        <Button onClick={handleSave}>
                            {t('articles', 'createArticle')}
                        </Button>
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
