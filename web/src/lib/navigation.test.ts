import { describe, expect, it } from 'vitest';

import { COMMAND_GROUPS, COMMAND_TAXONOMY } from '../../../shared/taxonomy';
import {
  getBreadcrumbForPath,
  getNavigationSections,
  getSimpleNavigationSections,
  getRouteRedirect,
  getRouteTitle,
  type NavigationSection,
} from './navigation';

describe('shared taxonomy', () => {
  it('exposes the 11 top-level command groups in CLI order', () => {
    expect(COMMAND_GROUPS).toEqual([
      'home',
      'build',
      'import',
      'eval',
      'optimize',
      'review',
      'deploy',
      'observe',
      'govern',
      'integrations',
      'settings',
    ]);
  });

  it('describes the build workflow tabs', () => {
    expect(COMMAND_TAXONOMY.build.subcommands).toEqual([
      'prompt',
      'transcript',
      'builder_chat',
      'saved_artifacts',
    ]);
  });
});

describe('navigation schema', () => {
  const sections: NavigationSection[] = getNavigationSections();

  it('keeps the shared CLI taxonomy order and adds help before settings', () => {
    expect(sections.map((section) => section.group)).toEqual([
      ...COMMAND_GROUPS.slice(0, -1),
      'help',
      'settings',
    ]);
  });

  it('maps build and optimize routes to the unified sections', () => {
    expect(getRouteTitle('/build')).toBe('Build');
    expect(getRouteTitle('/intelligence')).toBe('Build');
    expect(getRouteTitle('/optimize')).toBe('Optimize');
    expect(getRouteTitle('/live-optimize')).toBe('Live Optimize');
    expect(getRouteTitle('/improvements')).toBe('Improvements');
  });

  it('returns route redirects for legacy build and improvement pages', () => {
    expect(getRouteRedirect('/intelligence')).toBe('/build?tab=transcript');
    expect(getRouteRedirect('/builder')).toBe('/build?tab=builder-chat');
    expect(getRouteRedirect('/builder/demo')).toBe('/build?tab=builder-chat');
    expect(getRouteRedirect('/agent-studio')).toBe('/build?tab=builder-chat');
    expect(getRouteRedirect('/assistant')).toBe('/build?tab=builder-chat');
    expect(getRouteRedirect('/eval')).toBe('/evals');
    expect(getRouteRedirect('/review')).toBe('/improvements?tab=review');
    expect(getRouteRedirect('/changes')).toBe('/improvements?tab=review');
    expect(getRouteRedirect('/experiments')).toBe('/improvements?tab=experiments');
    expect(getRouteRedirect('/opportunities')).toBe('/improvements?tab=opportunities');
  });

  it('returns breadcrumbs from the shared taxonomy', () => {
    expect(getBreadcrumbForPath('/build')).toEqual(['Build']);
    expect(getBreadcrumbForPath('/improvements')).toEqual(['Review']);
    expect(getBreadcrumbForPath('/setup')).toEqual(['Home']);
    expect(getBreadcrumbForPath('/connect')).toEqual(['Import']);
    expect(getBreadcrumbForPath('/cli')).toEqual(['Help']);
    expect(getBreadcrumbForPath('/docs')).toEqual(['Help']);
    expect(getBreadcrumbForPath('/settings')).toEqual(['Settings']);
  });

  it('includes the guided connect flow in the import section', () => {
    const importSection = sections.find((section) => section.group === 'import');

    expect(importSection?.items.map((item) => item.path)).toEqual([
      '/connect',
      '/cx/studio',
      '/adk/import',
      '/cx/import',
    ]);
    expect(getRouteTitle('/connect')).toBe('Connect');
  });

  it('returns a smaller simple-mode navigation surface for the sidebar toggle', () => {
    const simpleSections = getSimpleNavigationSections();

    expect(simpleSections.length).toBeLessThan(sections.length);
    expect(simpleSections.flatMap((section) => section.items.map((item) => item.path))).toEqual([
      '/dashboard',
      '/setup',
      '/build',
      '/connect',
      '/cx/studio',
      '/adk/import',
      '/evals',
      '/results',
      '/compare',
      '/optimize',
      '/improvements',
      '/deploy',
      '/cli',
      '/docs',
    ]);
  });

  it('adds a dedicated help section with CLI and docs links', () => {
    const helpSection = sections.find((section) => section.group === 'help');

    expect(helpSection?.label).toBe('Help');
    expect(helpSection?.items).toEqual([
      { label: 'CLI', path: '/cli' },
      { label: 'Docs', path: '/docs' },
    ]);
    expect(getRouteTitle('/cli')).toBe('CLI');
    expect(getRouteTitle('/docs')).toBe('Documentation');
  });
});
