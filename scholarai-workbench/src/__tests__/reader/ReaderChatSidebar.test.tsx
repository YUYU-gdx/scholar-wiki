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
      getSession: vi.fn(),
      createSession: vi.fn(),
      sendMessage: vi.fn(),
      streamEvents: vi.fn(),
    },
  },
}));

describe('ReaderChatSidebar', () => {
  let source: MockEventSource;

  beforeEach(() => {
    vi.clearAllMocks();
    source = new MockEventSource();
    window.desktopShell = {
      runtime: 'electron',
      readLocalText: vi.fn().mockResolvedValue({ ok: true, data: '' }),
      writeLocalText: vi.fn().mockResolvedValue({ ok: true }),
    } as unknown as typeof window.desktopShell;
    vi.mocked(api.chat.getSession).mockResolvedValue({
      session: {
        session_id: 'session-1',
        title: 'Reader paper-1',
        default_mode: 'agent',
        library_id: 'library-1',
      },
      messages: [],
    });
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

    await waitFor(() => expect(window.desktopShell?.readLocalText).toHaveBeenCalled());
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Summarize this paper' } });
    await waitFor(() => expect(screen.getByRole('button', { name: /发送/ })).not.toBeDisabled());
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
    await waitFor(() => expect(window.desktopShell?.writeLocalText).toHaveBeenCalled());
  });

  it('restores the previous reader chat session from the markdown file', async () => {
    vi.mocked(window.desktopShell!.readLocalText).mockResolvedValue({
      ok: true,
      data: [
        '# Paper',
        '',
        '<!-- scholar-wiki-reader-chat-session {"libraryId":"library-1","paperId":"paper-1","sessionId":"session-existing"} -->',
        '',
      ].join('\n'),
    });
    vi.mocked(api.chat.getSession).mockResolvedValue({
      session: {
        session_id: 'session-existing',
        title: 'Reader paper-1',
        default_mode: 'agent',
        library_id: 'library-1',
      },
      messages: [{
        message_id: 'assistant-old',
        session_id: 'session-existing',
        role: 'assistant',
        content: 'Previous answer from this paper session.',
        status: 'completed',
      }],
    });

    render(
      <ReaderChatSidebar
        paperId="paper-1"
        libraryId="library-1"
        absolutePath="D:\\papers\\paper-1.md"
        isOpen
        onToggle={() => {}}
      />,
    );

    await waitFor(() => expect(api.chat.getSession).toHaveBeenCalledWith('session-existing', 'library-1'));
    expect(screen.getByText(/Previous answer from this paper session/)).toBeInTheDocument();
    expect(api.chat.createSession).not.toHaveBeenCalled();
  });
});
