using System;
using Windows.Security.Credentials;

namespace divoom_hub_winui3;

internal static class LocalTokenStore
{
    private static string Resource => Edition.ProfileName + ".TimesGate";

    private static PasswordCredential? Find(PasswordVault vault, string id)
    {
        try { return vault.Retrieve(Resource, id); }
        catch (Exception e) when ((uint)e.HResult == 0x80070490) { return null; }
    }

    public static string Read(string id = "LocalToken")
    {
        var credential = Find(new PasswordVault(), id);
        if (credential is null) return "";
        credential.RetrievePassword();
        return credential.Password;
    }

    public static void Save(string token, string id = "LocalToken")
    {
        var vault = new PasswordVault();
        var old = Find(vault, id);
        if (old is not null)
        {
            old.RetrievePassword();
            if (old.Password == token) return;
            vault.Remove(old);
        }
        try
        {
            if (token.Length > 0) vault.Add(new PasswordCredential(Resource, id, token));
        }
        catch
        {
            if (old is not null) vault.Add(old);
            throw;
        }
    }
}
