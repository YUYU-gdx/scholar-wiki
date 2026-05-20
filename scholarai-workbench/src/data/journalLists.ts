export type JournalListTag = 'UTD24' | 'FT50';

const UTD24_JOURNALS = [
  'The Accounting Review',
  'Journal of Accounting and Economics',
  'Journal of Accounting Research',
  'Journal of Finance',
  'Journal of Financial Economics',
  'The Review of Financial Studies',
  'Information Systems Research',
  'Journal on Computing',
  'INFORMS Journal on Computing',
  'MIS Quarterly',
  'Journal of Consumer Research',
  'Journal of Marketing',
  'Journal of Marketing Research',
  'Marketing Science',
  'Management Science',
  'Operations Research',
  'Journal of Operations Management',
  'Manufacturing and Service Operations Management',
  'Manufacturing & Service Operations Management',
  'Production and Operations Management',
  'Academy of Management Journal',
  'Academy of Management Review',
  'Administrative Science Quarterly',
  'Organization Science',
  'Journal of International Business Studies',
  'Strategic Management Journal',
];

const FT50_JOURNALS = [
  'Academy of Management Journal',
  'Academy of Management Review',
  'Accounting, Organizations and Society',
  'Accounting Review',
  'The Accounting Review',
  'Administrative Science Quarterly',
  'American Economic Review',
  'California Management Review',
  'Contemporary Accounting Research',
  'Econometrica',
  'Entrepreneurship Theory and Practice',
  'Harvard Business Review',
  'Human Relations',
  'Information Systems Research',
  'Journal of Accounting and Economics',
  'Journal of Accounting Research',
  'Journal of Applied Psychology',
  'Journal of Business Ethics',
  'Journal of Business Venturing',
  'Journal of Consumer Psychology',
  'Journal of Consumer Research',
  'Journal of Finance',
  'Journal of Financial and Quantitative Analysis',
  'Journal of Financial Economics',
  'Journal of International Business Studies',
  'Journal of Management',
  'Journal of Management Information Systems',
  'Journal of Marketing',
  'Journal of Marketing Research',
  'Journal of Operations Management',
  'Journal of Political Economy',
  'Journal of the Academy of Marketing Science',
  'Management Science',
  'Manufacturing and Service Operations Management',
  'Manufacturing & Service Operations Management',
  'Marketing Science',
  'MIS Quarterly',
  'Operations Research',
  'Organization Science',
  'Organization Studies',
  'Production and Operations Management',
  'Quarterly Journal of Economics',
  'RAND Journal of Economics',
  'Research Policy',
  'Review of Accounting Studies',
  'Review of Economic Studies',
  'Review of Finance',
  'Review of Financial Studies',
  'Sloan Management Review',
  'MIT Sloan Management Review',
  'Strategic Entrepreneurship Journal',
  'Strategic Management Journal',
];

function normalizeJournalName(value: string): string {
  return String(value || '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/^the\s+/i, '')
    .replace(/\bthe\s+/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

const JOURNAL_LISTS: Record<JournalListTag, Set<string>> = {
  UTD24: new Set(UTD24_JOURNALS.map(normalizeJournalName)),
  FT50: new Set(FT50_JOURNALS.map(normalizeJournalName)),
};

export function journalListTags(journal: string): JournalListTag[] {
  const normalized = normalizeJournalName(journal);
  if (!normalized) return [];
  const tags: JournalListTag[] = [];
  if (JOURNAL_LISTS.UTD24.has(normalized)) tags.push('UTD24');
  if (JOURNAL_LISTS.FT50.has(normalized)) tags.push('FT50');
  return tags;
}
