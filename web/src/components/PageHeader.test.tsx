import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { PageHeader } from './PageHeader';

describe('PageHeader', () => {
  it('sets a page-specific browser title', () => {
    render(<PageHeader title="Compare" description="Head-to-head evaluations." />);

    expect(screen.getByRole('heading', { name: 'Compare' })).toBeInTheDocument();
    expect(document.title).toBe('Compare • AutoAgent');
  });
});
