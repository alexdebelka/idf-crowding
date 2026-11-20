"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { readFavourites } from "@/lib/favourites";
import { notifyFavourites, notifyStationOpened, registerServiceWorker } from "./register";

/**
 * Registers the service worker (public/sw.js) once, in production, and tells it which station
 * page is showing (client-side navigation included) and which stations are favourites. Renders nothing.
 */
export function RegisterSW() {
  const pathname = usePathname();
  useEffect(() => {
    registerServiceWorker();
    notifyFavourites(readFavourites().map((p) => p.id));
  }, []);
  useEffect(() => {
    notifyStationOpened(pathname);
  }, [pathname]);
  return null;
}
