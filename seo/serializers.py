from rest_framework import serializers


class SEOFieldsSerializer(serializers.Serializer):
    metaTitle = serializers.CharField(allow_blank=True, default="")
    metaDescription = serializers.CharField(allow_blank=True, default="")
    metaKeywords = serializers.CharField(allow_blank=True, default="")
    ogTitle = serializers.CharField(allow_blank=True, default="")
    ogDescription = serializers.CharField(allow_blank=True, default="")
    ogImageUrl = serializers.URLField(allow_blank=True, default="")
    canonicalUrl = serializers.URLField(allow_blank=True, default="")


class SEOUpdateSerializer(serializers.Serializer):
    metaTitle = serializers.CharField(required=False, allow_blank=True, max_length=255)
    metaDescription = serializers.CharField(required=False, allow_blank=True)
    metaKeywords = serializers.CharField(required=False, allow_blank=True, max_length=255)
    ogTitle = serializers.CharField(required=False, allow_blank=True, max_length=255)
    ogDescription = serializers.CharField(required=False, allow_blank=True)
    ogImageUrl = serializers.URLField(required=False, allow_blank=True)
    canonicalUrl = serializers.URLField(required=False, allow_blank=True)


class SEOUpdateRequestSerializer(serializers.Serializer):
    seo = SEOUpdateSerializer()


class StoreSEOResponseSerializer(serializers.Serializer):
    store_id = serializers.IntegerField()
    seo = SEOFieldsSerializer()


class ProductSEOResponseSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    store_id = serializers.IntegerField()
    seo = SEOFieldsSerializer()


class CategorySEOResponseSerializer(serializers.Serializer):
    category_id = serializers.IntegerField()
    store_id = serializers.IntegerField()
    seo = SEOFieldsSerializer()
