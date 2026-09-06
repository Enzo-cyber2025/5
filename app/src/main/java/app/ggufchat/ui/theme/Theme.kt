package app.ggufchat.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext

private val DarkColors = darkColorScheme(
    primary = Color(0xFF7EE0A3),
    onPrimary = Color(0xFF00210F),
    primaryContainer = Color(0xFF0D3B22),
    onPrimaryContainer = Color(0xFFA4F7C2),
    secondary = Color(0xFF5FD0C8),
    background = Color(0xFF0E1113),
    onBackground = Color(0xFFE6E9E6),
    surface = Color(0xFF14181B),
    onSurface = Color(0xFFE6E9E6),
    surfaceVariant = Color(0xFF1E2427),
    onSurfaceVariant = Color(0xFFB6C2BC),
    outline = Color(0xFF3C4742),
    error = Color(0xFFFFB4AB),
    surfaceContainer = Color(0xFF1A1F22),
    surfaceContainerHigh = Color(0xFF1F2528),
    surfaceContainerHighest = Color(0xFF242B2E)
)

private val LightColors = lightColorScheme(
    primary = Color(0xFF006E3A),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFF8CF5B2),
    onPrimaryContainer = Color(0xFF00210F),
    secondary = Color(0xFF006A66),
    background = Color(0xFFF7FAF7),
    onBackground = Color(0xFF181D1A),
    surface = Color(0xFFF7FAF7),
    onSurface = Color(0xFF181D1A),
    surfaceVariant = Color(0xFFDDE6DE),
    onSurfaceVariant = Color(0xFF414B44),
    outline = Color(0xFF717B73),
    surfaceContainer = Color(0xFFECF0EC),
    surfaceContainerHigh = Color(0xFFE6EAE6),
    surfaceContainerHighest = Color(0xFFE0E5E0)
)

@Composable
fun GgufTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    dynamicColor: Boolean = false,
    content: @Composable () -> Unit
) {
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val context = LocalContext.current
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        }
        darkTheme -> DarkColors
        else -> LightColors
    }
    MaterialTheme(colorScheme = colorScheme, content = content)
}
