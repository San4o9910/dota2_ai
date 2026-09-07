"use client";

import { useSyncExternalStore } from "react";

const STORAGE_KEY = "narma-show-estimated-map-data";
const CHANGE_EVENT = "narma-estimated-map-data-change";

function subscribe(onStoreChange: () => void) {
  window.addEventListener("storage", onStoreChange);
  window.addEventListener(CHANGE_EVENT, onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener(CHANGE_EVENT, onStoreChange);
  };
}

function getSnapshot() {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function useEstimatedMapData() {
  return useSyncExternalStore(subscribe, getSnapshot, () => false);
}

export function setEstimatedMapData(enabled: boolean) {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(enabled));
  } catch {
    // The interface still updates for this tab when storage is unavailable.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}
