import { useEffect, useRef } from 'react';
import type { Annotation } from './types';

interface PdfAnnotationsProps {
  annotations: Annotation[];
  currentPage: number;
  scale: number;
  containerRef: React.RefObject<HTMLDivElement | null>;
}

export default function PdfAnnotations({ annotations, currentPage, scale, containerRef }: PdfAnnotationsProps) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!containerRef.current || !svgRef.current) return;
    const container = containerRef.current;
    const svg = svgRef.current;

    svg.innerHTML = '';
    const pageAnn = annotations.filter((a) => a.page_index === currentPage - 1);
    if (pageAnn.length === 0) return;

    const canvas = container.querySelector('canvas');
    if (!canvas) return;

    svg.setAttribute('width', String(canvas.width));
    svg.setAttribute('height', String(canvas.height));
    svg.style.position = 'absolute';
    svg.style.top = '0';
    svg.style.left = '0';
    svg.style.pointerEvents = 'none';

    for (const ann of pageAnn) {
      if (ann.type === 'highlight' || ann.type === 'underline') {
        for (const rect of ann.rects) {
          if (rect.page_index !== currentPage - 1) continue;
          const el = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
          el.setAttribute('x', String(rect.x * scale));
          el.setAttribute('y', String(rect.y * scale));
          el.setAttribute('width', String(rect.width * scale));
          el.setAttribute('height', String(rect.height * scale));
          el.setAttribute('fill', ann.type === 'highlight' ? ann.color + '40' : 'none');
          if (ann.type === 'underline') {
            el.setAttribute('stroke', ann.color);
            el.setAttribute('stroke-width', '2');
          }
          svg.appendChild(el);
        }
      }
    }
  }, [annotations, currentPage, scale, containerRef]);

  return <svg ref={svgRef} />;
}
