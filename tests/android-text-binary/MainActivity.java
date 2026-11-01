package com.example.textbinary;

import android.app.Activity;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class MainActivity extends Activity {
    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(24, 32, 24, 24);

        TextView title = new TextView(this);
        title.setText("Texto para binário");
        title.setTextSize(24);
        layout.addView(title, new LinearLayout.LayoutParams(-1, -2));

        EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setHint("Digite um texto");
        input.setContentDescription("text-input");
        layout.addView(input, new LinearLayout.LayoutParams(-1, -2));

        Button convert = new Button(this);
        convert.setText("Converter");
        convert.setContentDescription("convert-button");
        layout.addView(convert, new LinearLayout.LayoutParams(-1, -2));

        TextView result = new TextView(this);
        result.setTextIsSelectable(true);
        result.setTextSize(18);
        result.setContentDescription("binary-result");
        LinearLayout.LayoutParams resultParams = new LinearLayout.LayoutParams(-1, -2);
        resultParams.topMargin = 24;
        layout.addView(result, resultParams);

        convert.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                result.setText(toBinary(input.getText().toString()));
            }
        });
        setContentView(layout, new ViewGroup.LayoutParams(-1, -1));
    }

    private static String toBinary(String text) {
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < text.length(); i++) {
            if (i > 0) out.append(' ');
            String bits = Integer.toBinaryString(text.charAt(i));
            for (int pad = bits.length(); pad < 8; pad++) out.append('0');
            out.append(bits);
        }
        return out.toString();
    }
}
