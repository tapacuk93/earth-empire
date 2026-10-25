# kotlinx.serialization: keep generated serializers of the contract's classes.
-keepattributes *Annotation*, InnerClasses
-keepclassmembers class com.oeaio.earthempire.data.** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class com.oeaio.earthempire.data.**$$serializer { *; }
