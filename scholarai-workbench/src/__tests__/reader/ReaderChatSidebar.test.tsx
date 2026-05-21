import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ReaderChatSidebar from '../../components/reader/ReaderChatSidebar';
import { api } from '../../api';

class MockEventSource {
  listeners = new Map<string, Array<(event: MessageEvent) => void>>();
  closed = false;

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    const current = this.listeners.get(type) || [];
    current.push(listener);
    this.listeners.set(type, current);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, payload: unknown) {
    const event = new MessageEvent(type, { data: JSON.stringify(payload) });
    for (const listener of this.listeners.get(type) || []) {
      listener(event);
    }
  }
}

vi.mock('../../api', () => ({
  api: {
    chat: {
      createSession: vi.fn(),
      sendMessage: vi.fn(),
      streamEvents: vi.fn(),
    },
  },
}));

describe('ReaderChatSidebar', () => {
  let source: MockEventSource;

  beforeEach(() => {
    source = new MockEventSource();
    vi.mocked(api.chat.createSession).mockResolvedValue({
      session_id: 'session-1',
      title: 'Reader paper-1',
      default_mode: 'agent',
      library_id: 'library-1',
    });
    vi.mocked(api.chat.sendMessage).mockResolvedValue({
      session_id: 'session-1',
      user_message_id: 'user-1',
      assistant_message_id: 'assistant-1',
      stream_url: '/stream',
    });
    vi.mocked(api.chat.streamEvents).mockReturnValue(source as unknown as EventSource);
  });

  it('renders the complete final assistant answer when tool trace events are present', async () => {
    const fullAnswer = [
      '# Final Summary',
      '',
      'Opening paragraph: the paper studies adoption behavior with evidence from survey data.',
      '',
      '## Evidence',
      '',
      '- First complete bullet includes the independent variable.',
      '- Second complete bullet includes the dependent variable.',
      '',
      '```text',
      'MODEL: adoption_intention = trust + usefulness',
      '```',
      '',
      'Closing sentence: all requested sections are rendered through the end.',
    ].join('\n');

    render(
      <ReaderChatSidebar
        paperId="paper-1"
        libraryId="library-1"
        absolutePath="D:\\papers\\paper-1.md"
        isOpen
        onToggle={() => {}}
      />,
    );

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Summarize this paper' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });

    await waitFor(() => expect(api.chat.streamEvents).toHaveBeenCalledWith('session-1', 'assistant-1'));

    act(() => {
      source.emit('tool_call', {
        name: 'rag_search',
        arguments: { query: 'paper summary' },
        result: { hits: [{ paper_id: 'paper-1' }] },
      });
      source.emit('completed', {
        answer: fullAnswer,
        tool_trace: [{
          event: 'tool_call',
          name: 'rag_search',
          arguments: { query: 'paper summary' },
          result: { hits: [{ paper_id: 'paper-1' }] },
        }],
      });
    });

    const assistantMessages = screen.getAllByText((_, element) => (
      element?.textContent?.includes('Final Summary')
      && element.textContent.includes('Opening paragraph: the paper studies adoption behavior with evidence from survey data.')
      && element.textContent.includes('Evidence')
      && element.textContent.includes('First complete bullet includes the independent variable.')
      && element.textContent.includes('Second complete bullet includes the dependent variable.')
      && element.textContent.includes('MODEL: adoption_intention = trust + usefulness')
      && element.textContent.includes('Closing sentence: all requested sections are rendered through the end.')
    ));
    expect(assistantMessages.length).toBeGreaterThan(0);
    expect(screen.getByText(/RAG/)).toBeInTheDocument();
  });
});
