import React, { createContext, useContext, useEffect, useRef } from 'react';
import { AnalyticsTracker, TrackerOptions, ConsentLevel } from '@analytics/browser';

interface AnalyticsContextType {
  tracker: AnalyticsTracker | null;
  trackPageview: (path?: string) => void;
  trackEvent: (name: string, type?: string, metadata?: Record<string, any>) => void;
  setConsent: (level: ConsentLevel) => void;
}

const AnalyticsContext = createContext<AnalyticsContextType>({
  tracker: null,
  trackPageview: () => {},
  trackEvent: () => {},
  setConsent: () => {},
});

export const AnalyticsProvider: React.FC<{ options: TrackerOptions; children: React.ReactNode }> = ({
  options,
  children,
}) => {
  const trackerRef = useRef<AnalyticsTracker | null>(null);

  if (!trackerRef.current) {
    trackerRef.current = new AnalyticsTracker(options);
  }

  const trackPageview = (path?: string) => {
    trackerRef.current?.trackPageview(path);
  };

  const trackEvent = (name: string, type: string = 'custom', metadata?: Record<string, any>) => {
    trackerRef.current?.trackEvent(name, type, metadata);
  };

  const setConsent = (level: ConsentLevel) => {
    trackerRef.current?.setConsent(level);
  };

  return (
    <AnalyticsContext.Provider value={{ tracker: trackerRef.current, trackPageview, trackEvent, setConsent }}>
      {children}
    </AnalyticsContext.Provider>
  );
};

export const useAnalytics = () => useContext(AnalyticsContext);

// Example Consumer Component
export const SampleEcommerceCheckout: React.FC = () => {
  const { trackEvent } = useAnalytics();

  const handlePurchase = () => {
    trackEvent('purchase_complete', 'click', {
      order_id: 'ord_98765',
      value: 49.99,
    });
  };

  return (
    <div>
      <h2>Checkout Confirmation</h2>
      <button onClick={handlePurchase}>Complete Purchase</button>
    </div>
  );
};
