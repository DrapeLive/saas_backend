# Merge migration for conflicting 0005 branches
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0005_remove_product_products_pr_company_3b138a_idx_and_more"),
        ("products", "0010_remove_category_description_remove_category_image_and_more"),
    ]

    operations = [
    ]
