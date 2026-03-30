import { describe, expect, it } from 'vitest';

import { COMMAND_GROUPS, COMMAND_TAXONOMY } from '../../../shared/taxonomy';
import {
  getBreadcrumbForPath,
  getNavigationSections,
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

  it('groups routes by the shared CLI taxonomy', () => {
    expect(sections.map((section) => section.group)).toEqual(COMMAND_GROUPS);
  });

  it('maps build and optimize routes to the unified sections', () => {
    expect(getRouteTitle('/build')).toBe('Build');
    expect(getRouteTitle('/intelligence')).toBe('Build');
    expect(getRouteTitle('/optimize')).toBe('Optimize');
    expect(getRouteTitle('/live-optimize')).toBe('Optimize');
  });

  it('returns route redirects for legacy build pages', () => {
    expect(getRouteRedirect('/intelligence')).toBe('/build?tab=transcript');
    expect(getRouteRedirect('/builder')).toBe('/build?tab=builder-chat');
    expect(getRouteRedirect('/builder/demo')).toBe('/build?tab=builder-chat');
    expect(getRouteRedirect('/agent-studio')).toBe('/build?tab=builder-chat');
    expect(getRouteRedirect('/assistant')).toBe('/build?tab=builder-chat');
  });

  it('returns breadcrumbs from the shared taxonomy', () => {
    expect(getBreadcrumbForPath('/build')).toEqual(['Build']);
    expect(getBreadcrumbForPath('/changes')).toEqual(['Optimize', 'Review']);
    expect(getBreadcrumbForPath('/setup')).toEqual(['Home']);
    expect(getBreadcrumbForPath('/settings')).toEqual(['Settings']);
  });
});
