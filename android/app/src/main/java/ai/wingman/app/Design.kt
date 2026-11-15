package ai.wingman.app

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.abs
import kotlin.math.sin

// Wingman's look: paper and ink, one blue, an editorial serif for anything Wingman "says",
// a plain sans for controls, and a monospace for times and labels.

val Paper = Color(0xFFF7F8FB)
val Ink = Color(0xFF0B1026)
val Muted = Color(0xFF646C87)
val Hair = Color(0xFFE3E6EF)
val Accent = Color(0xFF2B50FF)
val AccentSoft = Color(0xFFE8EDFF)
val Night = Color(0xFF070B1C)
val NightText = Color(0xFFAEB6D6)
val Due = Color(0xFFB86E00)
val DueSoft = Color(0xFFFFF1D9)
val Good = Color(0xFF14804A)
val GoodSoft = Color(0xFFDDF5E8)
val Bad = Color(0xFFB3261E)
val BadSoft = Color(0xFFFDE7E4)

val Serif = FontFamily(
    Font(R.font.instrument_serif),
    Font(R.font.instrument_serif_italic, style = FontStyle.Italic),
)

@OptIn(ExperimentalTextApi::class)
private fun weight(resource: Int, value: Int) =
    Font(resource, FontWeight(value), variationSettings = FontVariation.Settings(FontVariation.weight(value)))

val Sans = FontFamily(weight(R.font.geist, 400), weight(R.font.geist, 500), weight(R.font.geist, 600), weight(R.font.geist, 700))
val Mono = FontFamily(weight(R.font.geist_mono, 400), weight(R.font.geist_mono, 500))

/** The dark surface used for the hero card and onboarding: ink with a blue glow in one corner. */
fun Modifier.night(): Modifier = drawBehind {
    drawRect(Night)
    drawCircle(
        Brush.radialGradient(listOf(Color(0xFF3558FF), Color(0x663558FF), Color(0x00070B1C)),
            center = Offset(size.width * 0.92f, size.height * 0.02f), radius = size.width * 0.95f),
        radius = size.width * 0.95f, center = Offset(size.width * 0.92f, size.height * 0.02f),
    )
    drawCircle(
        Brush.radialGradient(listOf(Color(0x5522C7E8), Color(0x00070B1C)),
            center = Offset(size.width * 0.05f, size.height * 1.02f), radius = size.width * 0.7f),
        radius = size.width * 0.7f, center = Offset(size.width * 0.05f, size.height * 1.02f),
    )
}

/** Serif text: headlines, and anything in Wingman's own voice. */
@Composable
fun Display(text: String, size: TextUnit, color: Color = Ink, italic: Boolean = false, modifier: Modifier = Modifier, maxLines: Int = Int.MAX_VALUE) =
    Text(text, fontFamily = Serif, fontSize = size, lineHeight = size * 1.08f, color = color, letterSpacing = (-0.3).sp,
        fontStyle = if (italic) FontStyle.Italic else FontStyle.Normal, modifier = modifier, maxLines = maxLines, overflow = TextOverflow.Ellipsis)

/** Sans text for everything functional. */
@Composable
fun Body(text: String, size: TextUnit = 15.sp, color: Color = Ink, weight: FontWeight = FontWeight.Normal, modifier: Modifier = Modifier, maxLines: Int = Int.MAX_VALUE) =
    Text(text, fontFamily = Sans, fontSize = size, lineHeight = size * 1.42f, color = color, fontWeight = weight, modifier = modifier,
        maxLines = maxLines, overflow = TextOverflow.Ellipsis)

/** Small capitals in monospace: section labels, times, states. */
@Composable
fun Label(text: String, color: Color = Muted, modifier: Modifier = Modifier) =
    Text(text.uppercase(), fontFamily = Mono, fontSize = 11.sp, letterSpacing = 1.3.sp, color = color, fontWeight = FontWeight.Medium,
        modifier = modifier, maxLines = 1, overflow = TextOverflow.Ellipsis)

@Composable
fun Rule(color: Color = Hair) = Box(Modifier.fillMaxWidth().height(1.dp).background(color))

/**
 * Wingman's signature: a row of bars that breathes on its own and swells with the microphone.
 * `level` is 0 to 1; `active` false flattens it to a resting line.
 */
@Composable
fun Wave(level: Float, active: Boolean, color: Color, modifier: Modifier = Modifier, bars: Int = 40) {
    val phase by rememberInfiniteTransition(label = "wave").animateFloat(
        0f, (2 * Math.PI).toFloat(), infiniteRepeatable(tween(2600, easing = LinearEasing)), label = "phase")
    val swell by animateFloatAsState(if (active) 0.22f + level.coerceIn(0f, 1f) * 0.78f else 0.06f, tween(140), label = "swell")
    Canvas(modifier) {
        val slot = size.width / bars
        val thick = slot * 0.46f
        for (index in 0 until bars) {
            val across = index / (bars - 1f)
            val envelope = sin(across * Math.PI).toFloat() // tall in the middle, low at the ends
            val ripple = abs(sin(phase + index * 0.52f)) * 0.65f + abs(sin(phase * 1.7f + index * 0.21f)) * 0.35f
            val tall = size.height * (0.06f + swell * envelope * ripple).coerceAtMost(1f)
            drawRoundRect(color.copy(alpha = 0.35f + 0.65f * envelope), Offset(index * slot + (slot - thick) / 2, (size.height - tall) / 2),
                Size(thick, tall), CornerRadius(thick / 2))
        }
    }
}

/** A pill button. `solid` fills it with ink (or white on a dark surface). */
@Composable
fun Action(text: String, solid: Boolean = false, onDark: Boolean = false, enabled: Boolean = true, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val fill = when { !solid -> Color.Transparent; onDark -> Color.White; else -> Ink }
    val ink = when { solid && onDark -> Night; solid -> Color.White; onDark -> Color.White; else -> Ink }
    Box(
        modifier.height(46.dp).clip(RoundedCornerShape(23.dp)).background(fill)
            .then(if (solid) Modifier else Modifier.border(1.dp, if (onDark) Color(0x40FFFFFF) else Hair, RoundedCornerShape(23.dp)))
            .clickable(enabled = enabled, onClick = onClick).padding(horizontal = 18.dp),
        contentAlignment = Alignment.Center,
    ) { Text(text, fontFamily = Sans, color = if (enabled) ink else ink.copy(alpha = 0.4f), fontSize = 14.sp, fontWeight = FontWeight.SemiBold, maxLines = 1) }
}
