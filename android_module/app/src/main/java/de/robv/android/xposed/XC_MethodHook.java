package de.robv.android.xposed;

import java.lang.reflect.Member;

/** Compile-time stub; the real implementation comes from LSPosed at runtime. */
public class XC_MethodHook {

    public XC_MethodHook() {}

    protected void beforeHookedMethod(MethodHookParam param) throws Throwable {}

    protected void afterHookedMethod(MethodHookParam param) throws Throwable {}

    public static class MethodHookParam {
        public Member method;
        public Object thisObject;
        public Object[] args;

        private Object result = null;
        private Throwable throwable = null;
        private boolean hasThrowable = false;

        public Object getResult() {
            return result;
        }

        public void setResult(Object result) {
            this.result = result;
            this.throwable = null;
            this.hasThrowable = false;
        }

        public Throwable getThrowable() {
            return throwable;
        }

        public boolean hasThrowable() {
            return hasThrowable;
        }

        public void setThrowable(Throwable throwable) {
            this.throwable = throwable;
            this.hasThrowable = true;
        }

        public Object getResultOrThrowable() throws Throwable {
            if (hasThrowable) throw throwable;
            return result;
        }
    }

    public static final class Unhook {
        public void unhook() {}
    }
}
