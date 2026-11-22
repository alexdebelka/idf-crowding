// "Envoyer au porte-clés": hands the favourite stations to the à point keychain
// (keychain/ in this repository). The keychain, in setup mode, runs its own Wi-Fi network and
// answers at this address; the phone joins that network and opens the link. A plain link,
// not a request from the page: nothing is sent unless the person taps it, and it goes to the
// keychain only, never to a server.
import type { SavedPlace } from "./saved";

export const KEYCHAIN_ORIGIN = "http://192.168.4.1";
/** Same limits as the keychain (keychain/apoint/model.h MAX_FAVS, store.cpp validId). */
export const KEYCHAIN_MAX = 12;
const ID = /^[A-Za-z0-9_-]{1,15}$/;

/** Link that gives the keychain these stations, in order; null when none can be sent. */
export function keychainLink(favourites: SavedPlace[]): string | null {
  const ids = favourites
    .map((p) => p.id)
    .filter((id) => ID.test(id))
    .slice(0, KEYCHAIN_MAX);
  return ids.length ? `${KEYCHAIN_ORIGIN}/f?ids=${ids.join(",")}` : null;
}
