// Self-contained: Puppeteer serializes each exported function on its own into
// the WhatsApp page, so nothing here may reach a helper outside the function
// that uses it. Only type annotations Babel erases are allowed.
//
// The account's own profile as WhatsApp Web holds it: display name, About text
// and whether a photo is set. Each part is read on its own, so one that cannot
// be read leaves the others intact; a part that could not be read is null,
// which is not the same as "empty". The photo's address is deliberately not
// returned: the window only says whether there is one.
//
// Nothing here returns a native exception's text: WhatsApp's errors can carry
// phone numbers and contact names.
export async function readMyProfile() {
  const profile = globalThis['WPP']?.profile;
  const answer: { name: string | null; status: string | null; photo: boolean | null } = {
    name: null,
    status: null,
    photo: null,
  };
  try {
    const name = profile.getMyProfileName();
    if (typeof name === 'string') answer.name = name;
  } catch {
    // Stays null: not readable on this WhatsApp Web build.
  }
  try {
    const status = await profile.getMyStatus();
    // An account with no About text answers undefined: that is "empty", not
    // "unreadable".
    answer.status = typeof status === 'string' ? status : '';
  } catch {
    // Stays null.
  }
  try {
    const picture = await profile.getMyProfilePicture();
    answer.photo = !!(
      picture &&
      (picture.eurl || picture.previewEurl || picture.img || picture.imgFull)
    );
  } catch {
    // Stays null: a failed lookup is not proof that there is no photo.
  }
  return answer;
}
