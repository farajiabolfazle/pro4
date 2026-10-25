package de.robv.android.xposed;

import de.robv.android.xposed.callbacks.XC_LoadPackage;

/**
 * Compile-time stub of the Xposed API. At runtime LSPosed/Xposed provides
 * the real classes through the parent class loader, so these copies are
 * never actually loaded. They only exist so the module compiles without
 * downloading the Xposed API jar from an external repository.
 */
public interface IXposedHookLoadPackage {
    void handleLoadPackage(XC_LoadPackage.LoadPackageParam lpparam) throws Throwable;
}
