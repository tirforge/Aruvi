declare module 'plyr' {
  interface PlyrOptions {
    controls?: string[];
    settings?: string[];
    speed?: { selected?: number; options?: number[] };
    quality?: { default?: number; options?: number[] };
    i18n?: Record<string, string>;
    [key: string]: unknown;
  }

  interface PlyrSource {
    type: 'video' | 'audio';
    title?: string;
    sources: Array<{ src: string; type?: string; size?: number }>;
    poster?: string;
  }

  class Plyr {
    constructor(element: string | HTMLElement | HTMLVideoElement | HTMLAudioElement, options?: PlyrOptions);
    play(): Promise<void>;
    pause(): void;
    togglePlay(): void;
    stop(): void;
    restart(): void;
    get currentTime(): number;
    set currentTime(time: number);
    get duration(): number;
    get paused(): boolean;
    get playing(): boolean;
    source: string | PlyrSource;
    destroy(): void;
    on(event: string, fn: (...args: unknown[]) => void): void;
    once(event: string, fn: (...args: unknown[]) => void): void;
    off(event: string, fn: (...args: unknown[]) => void): void;
    static setup(elements: string | HTMLElement | NodeList | Array<HTMLElement>, options?: PlyrOptions): Plyr[];
    static supported(type: string): boolean;
  }

  export default Plyr;
}
