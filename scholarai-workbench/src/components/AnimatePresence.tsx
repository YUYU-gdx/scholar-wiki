import { useState, useEffect, useRef, useCallback } from 'react';

export function AnimatePresence({ children, mode }: { children: React.ReactNode; mode?: string }) {
  return <>{children}</>;
}