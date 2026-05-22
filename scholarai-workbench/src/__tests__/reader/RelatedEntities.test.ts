import { describe, expect, it } from 'vitest';
import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { formatMeasurementMethods } from '../../components/reader/RelatedEntities';
import RelatedEntities from '../../components/reader/RelatedEntities';

describe('formatMeasurementMethods', () => {
  it('joins backend measurement method objects into a readable string', () => {
    expect(formatMeasurementMethods([
      { variable: 'Trust', operationalized_as: ['Likert scale', 'survey items'] },
      { variable: 'Performance', operationalized_as: ['ROA'] },
    ])).toBe('Trust：Likert scale、survey items；Performance：ROA');
  });

  it('joins string lists and ignores empty values', () => {
    expect(formatMeasurementMethods(['Likert scale', '', 'ROA'])).toBe('Likert scale；ROA');
  });
});

describe('RelatedEntities', () => {
  it('renders related papers as reader-tab links', () => {
    const events: unknown[] = [];
    const listener = (event: Event) => events.push((event as CustomEvent).detail);
    window.addEventListener('open-reader-tab', listener);

    try {
      render(React.createElement(RelatedEntities, {
        paperId: 'paper-current',
        libraryId: 'lib-1',
        isOpen: true,
        onToggle: () => {},
        graphData: {
            nodes: [],
            edges: [],
            paper_map: {
              'lib-1::paper-current': {
                paper_id: 'paper-current',
                library_id: 'lib-1',
                title: 'Current paper',
                variable_definitions: [{ variable: 'AI washing', aliases: ['AIW'] }],
              },
              'lib-1::paper-related': {
                paper_id: 'paper-related',
                library_id: 'lib-1',
                title: 'Unveiling AI washing',
                variable_definitions: [{ variable: 'AI washing', aliases: ['AIW'] }],
              },
            },
          },
      }));

      fireEvent.click(screen.getByRole('button', { name: /Unveiling AI washing/ }));

      expect(events).toEqual([{
        paperId: 'paper-related',
        libraryId: 'lib-1',
        type: 'markdown',
      }]);
    } finally {
      window.removeEventListener('open-reader-tab', listener);
    }
  });
});
