package com.ggufchat.app;

import android.app.Activity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.*;
import android.text.TextUtils;
import java.util.ArrayList;

public final class CompactUi {
    private static int dp(View v, int n) { return Math.round(n * v.getResources().getDisplayMetrics().density); }
    public static void style(Button button) {
        button.setSingleLine(true);
        button.setMaxLines(1);
        button.setEllipsize(TextUtils.TruncateAt.END);
        button.setTextSize(12);
        button.setMinWidth(0); button.setMinimumWidth(0);
        button.setMinHeight(0); button.setMinimumHeight(0);
        button.setIncludeFontPadding(false);
        button.setPadding(dp(button, 10), 0, dp(button, 10), 0);
        button.setMaxWidth(dp(button, 200));
        ViewGroup.LayoutParams old = button.getLayoutParams();
        if (old == null) old = new LinearLayout.LayoutParams(-2, dp(button, 36));
        old.height = dp(button, 36);
        button.setLayoutParams(old);
    }
    public static void install(Activity activity, LinearLayout root, LinearLayout compose, Button thinking, Button search) {
        HorizontalScrollView tools = null;
        for (int i=0; i<root.getChildCount(); i++)
            if (root.getChildAt(i) instanceof HorizontalScrollView) tools=(HorizontalScrollView)root.getChildAt(i);
        if (tools == null || !(tools.getChildAt(0) instanceof LinearLayout))
            throw new IllegalStateException("Unexpected chat toolbar layout");
        LinearLayout row = (LinearLayout)tools.getChildAt(0);
        ArrayList<Button> buttons = new ArrayList<>();
        buttons.add(thinking); buttons.add(search);
        for (int i=0; i<row.getChildCount(); i++)
            if (row.getChildAt(i) instanceof Button) buttons.add((Button)row.getChildAt(i));
        ViewGroup oldModes = (ViewGroup)thinking.getParent();
        oldModes.removeView(thinking); oldModes.removeView(search);
        root.removeView(oldModes);
        row.removeAllViews();
        for (int i=0; i<buttons.size(); i++) {
            Button b=buttons.get(i); style(b);
            LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-2, dp(b,36));
            lp.setMarginEnd(i+1<buttons.size()?10:0); // requested physical pixels, not dp
            row.addView(b, lp);
        }
        row.setOrientation(LinearLayout.HORIZONTAL);
        tools.setHorizontalScrollBarEnabled(false);
        tools.setVisibility(View.GONE);
        tools.setContentDescription("Ferramentas da conversa");
        final HorizontalScrollView drawer=tools;
        for(int i=compose.getChildCount()-1;i>=0;i--)
            if(compose.getChildAt(i) instanceof Space) compose.removeViewAt(i);
        Button toggle=new Button(activity);
        toggle.setText("\uD83D\uDD27");
        toggle.setContentDescription("Alternar ferramentas");
        style(toggle); toggle.setTextSize(18);
        toggle.setPadding(0,0,0,0);
        LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(dp(toggle,36),dp(toggle,36));
        lp.setMargins(10,0,10,0);
        compose.addView(toggle,1,lp);
        toggle.setOnClickListener(v -> {
            boolean open=drawer.getVisibility()!=View.VISIBLE;
            drawer.setVisibility(open?View.VISIBLE:View.GONE);
            toggle.setSelected(open);
        });
        for(int i=0;i<compose.getChildCount();i++) {
            View v=compose.getChildAt(i);
            if(v instanceof EditText) ((EditText)v).setMaxLines(4);
        }
    }
}
