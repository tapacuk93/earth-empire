// Home's two parts: the owner's dedicated highlights first, then the common ones.
// PROVISIONAL until CONTRACT.md defines sections: a highlight is dedicated when the API marks it
// (`section: "dedicated"`, `kind: "dedicated"` or `dedicated: true`); every other highlight is
// common. A published hit goes to the section in its `section` field (default common). With no
// marks at all, Home shows one common part, as before.
import type { Highlight } from './types';
import type { Hit } from './monitor';

export type SectionId = 'dedicated' | 'common';
export const SECTION_TITLE: Record<SectionId, string> = { dedicated: 'About the owner', common: 'Everything else' };
export const SECTIONS: SectionId[] = ['dedicated', 'common'];

type Raw = Record<string, unknown>;
const norm = (v: unknown): SectionId | undefined => {
  const s = typeof v === 'object' && v ? (v as Raw).id ?? (v as Raw).section : v;
  return s === 'dedicated' || s === 'owner' ? 'dedicated' : s === 'common' ? 'common' : undefined;
};

export function highlightSection(h: Highlight): SectionId {
  const r = h as unknown as Raw;
  return norm(r.section) || norm(r.kind) || (r.dedicated === true ? 'dedicated' : 'common');
}

export const hitSection = (h: Hit): SectionId => norm((h as unknown as Raw).section) || 'common';

/** The monitor's suggestion for where a hit belongs, and why. */
export function hitSuggestion(h: Hit): { section: SectionId; reason?: string } | undefined {
  const r = h as unknown as Raw;
  const s = r.suggested_section ?? r.section_suggestion ?? r.suggestion;
  const section = norm(s);
  if (!section) return undefined;
  const reason = (typeof s === 'object' && s ? (s as Raw).reason : undefined) ?? r.suggested_section_reason ?? r.section_reason;
  return { section, reason: typeof reason === 'string' ? reason : undefined };
}
