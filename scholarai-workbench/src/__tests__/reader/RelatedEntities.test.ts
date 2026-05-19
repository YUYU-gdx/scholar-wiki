import { describe, expect, it } from 'vitest';
import { formatMeasurementMethods } from '../../components/reader/RelatedEntities';

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
