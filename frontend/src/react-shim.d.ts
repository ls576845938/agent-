declare module 'react' {
  export type FormEvent<T = Element> = {
    preventDefault(): void;
    currentTarget: T;
    target: EventTarget & T;
  };

  export type SetStateAction<T> = T | ((previous: T) => T);
  export type Dispatch<T> = (value: SetStateAction<T>) => void;

  export function useState<T>(initialState: T | (() => T)): [T, Dispatch<T>];
  export function useEffect(effect: () => void | (() => void) | Promise<void>, deps?: readonly unknown[]): void;
  export function useMemo<T>(factory: () => T, deps: readonly unknown[]): T;
  export function useRef<T>(initialState: T): {current: T};
  export function StrictMode(props: {children?: unknown}): unknown;
}

declare module 'react-dom/client' {
  export function createRoot(container: Element | DocumentFragment): {
    render(node: unknown): void;
  };
}

declare module 'react/jsx-runtime' {
  export const Fragment: unknown;
  export function jsx(type: unknown, props: unknown, key?: unknown): unknown;
  export function jsxs(type: unknown, props: unknown, key?: unknown): unknown;
}

declare namespace JSX {
  interface IntrinsicElements {
    [elementName: string]: any;
  }
}
